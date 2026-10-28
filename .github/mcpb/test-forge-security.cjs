// source: https://github.com/digitalbazaar/forge/blob/v1.4.1/tests/unit/rsa.js
// Exact upstream nested DigestAlgorithm forgery vector, without test bypass flags.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const test = require("node:test");
const forge = require(process.env.FORGE_REGRESSION_MODULE || "node-forge");

test("rejects the upstream CVE-2026-85393 forged RSA signature", () => {
  const modulus =
    "E932AC92252F585B3A80A4DD76A897C8B7652952FE788F6EC8DD640587A1EE56" +
    "47670A8AD4C2BE0F9FA6E49C605ADF77B5174230AF7BD50E5D6D6D6D28CCF0A8" +
    "86A514CC72E51D209CC772A52EF419F6A953F3135929588EBE9B351FCA61CED7" +
    "8F346FE00DBB6306E5C2A4C6DFC3779AF85AB417371CF34D8387B9B30AE46D7A" +
    "5FF5A655B8D8455F1B94AE736989D60A6F2FD5CADBFFBD504C5A756A2E6BB5CE" +
    "CC13BCA7503F6DF8B52ACE5C410997E98809DB4DC30D943DE4E812A47553DCE5" +
    "4844A78E36401D13F77DC650619FED88D8B3926E3D8E319C80C744779AC5D6AB" +
    "E252896950917476ECE5E8FC27D5F053D6018D91B502C4787558A002B9283DA7";
  const signature =
    "00000000000000000000000000000000000000000000000000000000000000" +
    "00000000000000000000000000000000000000000000000000000000000000" +
    "00000000000000000000000000000000000000000000000000000000000000" +
    "00000000000000000000000000000000000000000000000000000000000000" +
    "00000000000000000000000000000000000000000000000000000000000000" +
    "0000000000000000000000000000000032cbfd4a7adc7905583d7920d7165d" +
    "77cf8d6f4b19a4c14026dc9bf5576b2de2aab4a0dc9d8303ba8e365764f52a" +
    "49da7a2dfc5bed616f52d37d860cb283543d93fe1b73ca6379278422fd8821" +
    "eeeddc3a1bee99f9";
  const key = forge.pki.rsa.setPublicKey(
    new forge.jsbn.BigInteger(modulus, 16), new forge.jsbn.BigInteger("3"),
  );
  const digest = forge.md.sha256.create().update("hello world!");
  assert.throws(
    () => key.verify(digest.digest().getBytes(), forge.util.hexToBytes(signature)),
    /does not contain a valid RSASSA-PKCS1-v1_5 DigestInfo/,
  );
});

test("keeps valid Node-generated signatures and PEM Buffer input compatible", () => {
  // source: https://nodejs.org/api/crypto.html#cryptogeneratekeypairsynctype-options
  const pair = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  const pem = pair.publicKey.export({ type: "spki", format: "pem" });
  const publicKey = forge.pki.publicKeyFromPem(Buffer.from(pem));
  const message = Buffer.from("MCPB consumer signature compatibility");
  const signature = crypto.sign("sha256", message, pair.privateKey);
  const digest = forge.md.sha256.create().update(message.toString("binary"));
  assert.equal(publicKey.verify(digest.digest().getBytes(), signature.toString("binary")), true);
});
