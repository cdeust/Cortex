/**
 * arrow-ipc.js — Minimal Apache Arrow IPC stream decoder.
 *
 * Decodes the specific schema produced by the Cortex quadtree endpoint:
 *   id   : dictionary<int32, utf8>
 *   x    : float32
 *   y    : float32
 *   kind : dictionary<int32, utf8>
 *
 * Arrow IPC stream format (little-endian):
 *   For each message:
 *     [continuation: int32 = -1][size: int32][flatbuffer: size bytes]
 *     [padding to 8-byte boundary][body: sum_of_buffer_lengths bytes]
 *   Followed by EOS: continuation=-1, size=0.
 *
 * Message header_type values (Arrow format spec):
 *   1 = Schema, 2 = DictionaryBatch, 3 = RecordBatch
 *
 * Source: Apache Arrow IPC format specification
 * https://arrow.apache.org/docs/format/Columnar.html#ipc-streaming-format
 *
 * The browser's fetch() auto-decompresses Content-Encoding: gzip, so
 * arrayBuffer() returns raw Arrow IPC bytes (not gzip-wrapped).
 *
 * If any decoding step fails, parseQuadtreeIpc returns null.
 * The caller should fall back to graphology circular layout.
 */

/**
 * Decode a Cortex quadtree Arrow IPC stream buffer.
 * @param {ArrayBuffer} buf — raw Arrow IPC stream bytes
 * @returns {Map<string,{x:number,y:number}>|null}
 */
export function parseQuadtreeIpc(buf) {
  try {
    return _decode(buf);
  } catch (err) {
    console.warn("[arrow-ipc] parse failed, circular layout fallback:", err.message);
    return null;
  }
}

// ── IPC stream walker ──────────────────────────────────────────────────────

/**
 * @param {ArrayBuffer} buf
 * @returns {Map<string,{x:number,y:number}>}
 */
function _decode(buf) {
  const view = new DataView(buf);
  let off = 0;
  const total = buf.byteLength;

  const dicts = new Map();   // dictId → string[]
  let idDictId = 0;
  let positionMap = null;

  while (off + 8 <= total) {
    const msg = _readMessage(buf, view, off, total);
    if (!msg) break;
    off = msg.nextOff;

    const bodyEnd = off + msg.bodyLength;

    if (msg.type === 1) {
      // Schema: resolve dict ids for "id" and "kind" columns.
      const fields = _schemaFields(msg.headerBytes);
      for (const f of fields) {
        if (f.name === "id") idDictId = f.dictId;
      }
    } else if (msg.type === 2 && msg.bodyLength > 0) {
      // DictionaryBatch: decode string dictionary.
      const dictId = _dictBatchId(msg.headerBytes);
      const strings = _decodeDictBody(buf, off, msg.bodyLength, msg.headerBytes);
      if (strings) dicts.set(dictId, strings);
    } else if (msg.type === 3 && msg.bodyLength > 0) {
      // RecordBatch: decode id-indices + x/y float32 columns.
      positionMap = _decodeRecordBatch(buf, off, msg.headerBytes, dicts, idDictId);
    }

    off = bodyEnd;
    off = _align8(off);
    if (off <= msg.savedOff) break;  // safety: no forward progress
  }

  return positionMap || new Map();
}

// ── Message reader ─────────────────────────────────────────────────────────

/**
 * Read one IPC message from the stream at position `off`.
 * @returns {{type, headerBytes, bodyLength, nextOff, savedOff}|null}
 */
function _readMessage(buf, view, off, total) {
  const savedOff = off;
  if (off + 8 > total) return null;

  const cont = view.getInt32(off, true);
  off += 4;

  let fbSize;
  if (cont === -1) {
    fbSize = view.getInt32(off, true);
    off += 4;
    if (fbSize === 0) return null;  // EOS
  } else {
    // Legacy: cont IS the flatbuffer size (no continuation prefix).
    fbSize = cont;
    if (fbSize === 0) return null;
  }

  if (off + fbSize > total) return null;
  const headerBytes = new Uint8Array(buf, off, fbSize);
  off += fbSize;
  off = _align8(off);

  const type = _msgType(headerBytes);
  const bodyLength = _msgBodyLen(headerBytes);

  return { type, headerBytes, bodyLength, nextOff: off, savedOff };
}

// ── Flatbuffer field extraction ────────────────────────────────────────────
// Arrow IPC flatbuffers (Message.fbs) are little-endian.
// A flatbuffer table starts with a signed int32 vtable soffset.
// vtable layout: [size: int16][object_size: int16][field_offsets…: int16]
// Field N offset is at vtable + 4 + N*2.
// Object field is at object_start + field_offset_value.

/**
 * Message root offset helpers.
 * @param {Uint8Array} bytes
 * @returns {{dv, root, vtOff, vtSize}}
 */
function _msgRoot(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const root = dv.getInt32(0, true);
  const vtOff = root - dv.getInt32(root, true);
  const vtSize = dv.getInt16(vtOff, true);
  return { dv, root, vtOff, vtSize };
}

/**
 * Read the Message.header_type union tag (field index 2).
 * 1=Schema, 2=DictionaryBatch, 3=RecordBatch
 * @param {Uint8Array} bytes
 * @returns {number}
 */
function _msgType(bytes) {
  try {
    const { dv, root, vtOff, vtSize } = _msgRoot(bytes);
    // vtable: [size(2)][obj_size(2)][f0(2)][f1(2)][f2(2)=header_type] → offset 4+2*2=8
    if (vtSize <= 8) return 0;
    const fOff = dv.getInt16(vtOff + 8, true);
    return fOff !== 0 ? dv.getInt8(root + fOff) : 0;
  } catch (_) { return 0; }
}

/**
 * Read the Message.bodyLength (int64, field index 3).
 * Returns only the lower 32 bits — sufficient for payloads < 4 GB.
 * @param {Uint8Array} bytes
 * @returns {number}
 */
function _msgBodyLen(bytes) {
  try {
    const { dv, root, vtOff, vtSize } = _msgRoot(bytes);
    // field 3 → vtable offset 4+3*2=10
    if (vtSize <= 10) return 0;
    const fOff = dv.getInt16(vtOff + 10, true);
    return fOff !== 0 ? dv.getInt32(root + fOff, true) : 0;
  } catch (_) { return 0; }
}

/**
 * Extract field names and dict ids from a Schema message flatbuffer.
 * pyarrow encodes field names as UTF-8 inline strings. We rely on the
 * known fixed column order (id, x, y, kind) produced by the quadtree
 * handler, assigning dictId 0 to "id" and 1 to "kind".
 * @param {Uint8Array} bytes
 * @returns {Array<{name:string, dictId:number}>}
 */
function _schemaFields(bytes) {
  // The quadtree schema is fixed: [id(dict0), x(f32), y(f32), kind(dict1)].
  // pyarrow assigns dictionary ids in field-encounter order.
  void bytes;
  return [
    { name: "id",   dictId: 0 },
    { name: "x",    dictId: -1 },
    { name: "y",    dictId: -1 },
    { name: "kind", dictId: 1 },
  ];
}

/**
 * Extract the DictionaryBatch.id from a Message flatbuffer.
 * DictionaryBatch is the "header" union (field 1 in Message vtable).
 * DictionaryBatch.id is field 0 in the DictionaryBatch vtable.
 * @param {Uint8Array} bytes
 * @returns {number}
 */
function _dictBatchId(bytes) {
  try {
    const { dv, root, vtOff, vtSize } = _msgRoot(bytes);
    // header field (field 1) is at vtable offset 4+1*2=6.
    if (vtSize <= 6) return 0;
    const headerFOff = dv.getInt16(vtOff + 6, true);
    if (headerFOff === 0) return 0;

    // Follow the offset-encoded reference (soffset_t: value is relative).
    const headerRef = root + headerFOff;
    const headerStart = headerRef + dv.getInt32(headerRef, true);

    // DictionaryBatch vtable.
    const dvtOff = headerStart - dv.getInt32(headerStart, true);
    const dvtSize = dv.getInt16(dvtOff, true);
    if (dvtSize <= 4) return 0;

    const idFOff = dv.getInt16(dvtOff + 4, true);
    if (idFOff === 0) return 0;

    // id is int64; read lower 32 bits.
    return dv.getInt32(headerStart + idFOff, true);
  } catch (_) { return 0; }
}

// ── Buffer-length extraction ───────────────────────────────────────────────
// We need the Arrow buffer lengths for each column to know how many bytes
// to read from the IPC body. These are in the RecordBatch flatbuffer's
// buffers vector as {offset: int64, length: int64} pairs.
//
// Approach: heuristic scan for contiguous (offset, length) int64 pairs
// where offsets are non-decreasing and lengths are non-negative.
// This is simpler and more robust than full flatbuffer vtable traversal.

/**
 * @param {Uint8Array} bytes
 * @returns {{rowCount:number, bufLengths:number[]}}
 */
function _recordBatchMeta(bytes) {
  try {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const n = bytes.byteLength;
    const pairs = [];

    for (let i = 0; i + 15 < n; i += 8) {
      const lo = dv.getInt32(i, true);
      const hi = dv.getInt32(i + 4, true);
      const lenLo = dv.getInt32(i + 8, true);
      const lenHi = dv.getInt32(i + 12, true);
      if (hi === 0 && lenHi === 0 && lo >= 0 && lenLo >= 0) {
        pairs.push({ pos: i, offset: lo, length: lenLo });
      }
    }

    // Find longest run of non-decreasing offsets.
    let best = [];
    let run = [];
    for (const p of pairs) {
      if (run.length === 0 || p.offset >= run[run.length - 1].offset) {
        run.push(p);
      } else {
        if (run.length > best.length) best = run;
        run = [p];
      }
    }
    if (run.length > best.length) best = run;
    if (best.length < 2) return { rowCount: 0, bufLengths: null };

    const bufLengths = best.map(p => p.length);

    // Row count: largest plausible int32 in the 32 bytes before the first pair.
    let rowCount = 0;
    const scanFrom = Math.max(0, best[0].pos - 32);
    for (let i = scanFrom; i < best[0].pos; i += 4) {
      const v = dv.getInt32(i, true);
      const vhi = i + 4 < n ? dv.getInt32(i + 4, true) : 1;
      if (vhi === 0 && v > rowCount && v < 10_000_000) rowCount = v;
    }

    return { rowCount, bufLengths };
  } catch (_) {
    return { rowCount: 0, bufLengths: null };
  }
}

// ── Dictionary body decoder ────────────────────────────────────────────────

/**
 * Decode a DictionaryBatch IPC body into a string[].
 * UTF-8 array layout in body (no-null case from pyarrow):
 *   [validity bitmap: 0 bytes (omitted) or padded to 8]
 *   [int32 offsets: (n+1) × 4 bytes, padded to 8]
 *   [UTF-8 data: bytes, padded to 8]
 * @param {ArrayBuffer} buf
 * @param {number} bodyStart
 * @param {number} bodyLength
 * @param {Uint8Array} headerBytes
 * @returns {string[]|null}
 */
function _decodeDictBody(buf, bodyStart, bodyLength, headerBytes) {
  try {
    const { bufLengths } = _recordBatchMeta(headerBytes);
    if (!bufLengths || bufLengths.length < 2) return null;

    let validityLen, offsetsLen, dataLen;
    if (bufLengths.length >= 3) {
      [validityLen, offsetsLen, dataLen] = bufLengths;
    } else {
      validityLen = 0;
      [offsetsLen, dataLen] = bufLengths;
    }

    let pos = bodyStart;
    pos += validityLen;
    if (validityLen % 8 !== 0) pos += 8 - (validityLen % 8);

    const nOffsets = offsetsLen / 4;
    if (pos + offsetsLen > buf.byteLength) return null;
    const offsets = new Int32Array(buf, pos, nOffsets);
    pos += offsetsLen;
    if (offsetsLen % 8 !== 0) pos += 8 - (offsetsLen % 8);

    if (pos + dataLen > buf.byteLength) return null;
    const textBytes = new Uint8Array(buf, pos, dataLen);
    const dec = new TextDecoder("utf-8");
    const strings = [];
    for (let i = 0; i < nOffsets - 1; i++) {
      strings.push(dec.decode(textBytes.subarray(offsets[i], offsets[i + 1])));
    }
    return strings;
  } catch (err) {
    console.warn("[arrow-ipc] dict body error:", err.message);
    return null;
  }
}

// ── RecordBatch body decoder ───────────────────────────────────────────────

/**
 * Decode a RecordBatch body for schema (id dict<int32>, x f32, y f32, kind dict<int32>).
 * @param {ArrayBuffer} buf
 * @param {number} bodyStart
 * @param {Uint8Array} headerBytes
 * @param {Map<number,string[]>} dicts
 * @param {number} idDictId
 * @returns {Map<string,{x:number,y:number}>|null}
 */
function _decodeRecordBatch(buf, bodyStart, headerBytes, dicts, idDictId) {
  try {
    const { rowCount, bufLengths } = _recordBatchMeta(headerBytes);
    // Need 8 buffers: 2 per column × 4 columns.
    if (!bufLengths || bufLengths.length < 6) return null;

    let pos = bodyStart;

    function skip(len) {
      pos += len;
      if (len > 0 && len % 8 !== 0) pos += 8 - (len % 8);
    }

    function readInt32Arr(len) {
      if (pos + len > buf.byteLength) return new Int32Array(0);
      const arr = new Int32Array(buf, pos, len / 4);
      skip(len);
      return arr;
    }

    function readFloat32Arr(len) {
      if (pos + len > buf.byteLength) return new Float32Array(0);
      const arr = new Float32Array(buf, pos, len / 4);
      skip(len);
      return arr;
    }

    // Column 0 — id (dict<int32>): [validity][int32 indices]
    skip(bufLengths[0]);
    const idIdx = readInt32Arr(bufLengths[1]);

    // Column 1 — x (float32): [validity][float32 values]
    skip(bufLengths[2]);
    const xVals = readFloat32Arr(bufLengths[3]);

    // Column 2 — y (float32): [validity][float32 values]
    skip(bufLengths[4]);
    const yVals = readFloat32Arr(bufLengths[5]);

    const idDict = dicts.get(idDictId);
    if (!idDict) return null;

    const map = new Map();
    const count = Math.min(rowCount || idIdx.length, idIdx.length, xVals.length, yVals.length);
    for (let i = 0; i < count; i++) {
      const nodeId = idDict[idIdx[i]];
      if (nodeId !== undefined) map.set(nodeId, { x: xVals[i], y: yVals[i] });
    }
    return map;
  } catch (err) {
    console.warn("[arrow-ipc] record batch error:", err.message);
    return null;
  }
}

// ── Alignment helper ───────────────────────────────────────────────────────

/** Advance to next 8-byte boundary. */
function _align8(n) {
  const rem = n % 8;
  return rem === 0 ? n : n + (8 - rem);
}
