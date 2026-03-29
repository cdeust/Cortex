"""Dictionary learning via K-SVD and Orthogonal Matching Pursuit (OMP).

Extracted from sparse_dictionary.py to respect the 300-line file limit.
Contains the numerical core: OMP sparse coding, least-squares solver,
atom initialization (maximin distance), and K-SVD dictionary optimization.

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any

from mcp_server.shared.linear_algebra import (
    cosine_similarity,
    dot,
    norm,
    normalize,
    scale,
    subtract,
    zeros,
)

# ---------------------------------------------------------------------------
# Orthogonal Matching Pursuit (OMP)
# ---------------------------------------------------------------------------


def _solve_least_squares_1(
    G: list[list[float]],
    h: list[float],
) -> list[float]:
    """Solve 1x1 least-squares system."""
    return [h[0] / G[0][0]] if G[0][0] != 0 else [0]


def _solve_least_squares_2(
    G: list[list[float]],
    h: list[float],
) -> list[float]:
    """Solve 2x2 least-squares system via Cramer's rule."""
    det = G[0][0] * G[1][1] - G[0][1] * G[1][0]
    if abs(det) < 1e-12:
        return [0, 0]
    return [
        (h[0] * G[1][1] - h[1] * G[0][1]) / det,
        (G[0][0] * h[1] - G[1][0] * h[0]) / det,
    ]


def _det3(m: list[list[float]]) -> float:
    """Compute determinant of a 3x3 matrix."""
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _solve_least_squares_3(
    G: list[list[float]],
    h: list[float],
) -> list[float]:
    """Solve 3x3 least-squares system via Cramer's rule."""
    det_g = _det3(G)
    if abs(det_g) < 1e-12:
        return [0, 0, 0]
    result = []
    for col in range(3):
        M = [row[:] for row in G]
        for row in range(3):
            M[row][col] = h[row]
        result.append(_det3(M) / det_g)
    return result


def _solve_least_squares(
    atoms: list[list[float]],
    b: list[float],
    selected: list[int],
) -> list[float]:
    """Solve least-squares for the selected atom subset."""
    n = len(selected)
    if n == 0:
        return []

    G = [
        [dot(atoms[selected[i]], atoms[selected[j]]) for j in range(n)]
        for i in range(n)
    ]
    h = [dot(atoms[selected[i]], b) for i in range(n)]

    if n == 1:
        return _solve_least_squares_1(G, h)
    if n == 2:
        return _solve_least_squares_2(G, h)
    if n == 3:
        return _solve_least_squares_3(G, h)

    return [0] * n


def omp(
    signal: list[float],
    atoms: list[list[float]],
    sparsity: int,
) -> dict[str, Any]:
    """Orthogonal Matching Pursuit: greedily select sparse atom subset.

    Returns:
        Dict with 'indices', 'coefficients', and 'residual'.
    """
    K = len(atoms)
    residual = list(signal)
    selected_indices: list[int] = []

    for _ in range(sparsity):
        best_corr = -1.0
        best_idx = -1
        for k in range(K):
            if k in selected_indices:
                continue
            corr = abs(dot(residual, atoms[k]))
            if corr > best_corr:
                best_corr = corr
                best_idx = k

        if best_idx == -1 or best_corr < 1e-10:
            break
        selected_indices.append(best_idx)

        coefficients = _solve_least_squares(atoms, signal, selected_indices)
        residual = list(signal)
        for i, idx in enumerate(selected_indices):
            residual = subtract(residual, scale(atoms[idx], coefficients[i]))

    coefficients = _solve_least_squares(atoms, signal, selected_indices)
    return {
        "indices": selected_indices,
        "coefficients": coefficients,
        "residual": residual,
    }


# ---------------------------------------------------------------------------
# Atom initialization (maximin distance selection)
# ---------------------------------------------------------------------------


def initialize_atoms(
    data: list[list[float]],
    K: int,
) -> list[list[float]]:
    """Select K diverse atoms from data using maximin distance."""
    if not data:
        return []
    effective_k = min(K, len(data))
    selected = [0]
    min_dist = [float("inf")] * len(data)

    for _ in range(1, effective_k):
        last_idx = selected[-1]
        for i in range(len(data)):
            if i in selected:
                continue
            d = 1 - abs(cosine_similarity(data[i], data[last_idx]))
            min_dist[i] = min(min_dist[i], d)

        best_dist = -1.0
        best_idx = 0
        for i in range(len(data)):
            if i in selected:
                continue
            if min_dist[i] > best_dist:
                best_dist = min_dist[i]
                best_idx = i
        selected.append(best_idx)

    return [normalize(data[idx]) for idx in selected]


# ---------------------------------------------------------------------------
# K-SVD dictionary update
# ---------------------------------------------------------------------------


def _compute_atom_contribution(
    data: list[list[float]],
    encodings: list[dict[str, Any]],
    atoms: list[list[float]],
    atom_index: int,
    D: int,
) -> list[float]:
    """Sum partial reconstructions for users of a given atom."""
    users = _find_atom_users(encodings, atom_index)
    if not users:
        return zeros(D)

    contribution = zeros(D)
    for user in users:
        partial = list(data[user["dataIdx"]])
        enc = encodings[user["dataIdx"]]
        for j, aidx in enumerate(enc["indices"]):
            if aidx == atom_index:
                continue
            partial = subtract(partial, scale(atoms[aidx], enc["coefficients"][j]))
        for d_idx in range(D):
            contribution[d_idx] += partial[d_idx]

    return contribution


def _find_atom_users(
    encodings: list[dict[str, Any]],
    atom_index: int,
) -> list[dict[str, Any]]:
    """Find all data points that use a given atom."""
    users = []
    for i, enc in enumerate(encodings):
        if atom_index in enc["indices"]:
            idx = enc["indices"].index(atom_index)
            users.append({"dataIdx": i, "coeff": enc["coefficients"][idx]})
    return users


def update_dictionary(
    data: list[list[float]],
    atoms: list[list[float]],
    sparsity: int,
    iterations: int,
    D: int,
) -> list[list[float]]:
    """Run K-SVD iterations to refine dictionary atoms.

    Returns:
        Updated list of atom vectors.
    """
    actual_k = len(atoms)
    atoms = [list(a) for a in atoms]

    for _ in range(iterations):
        encodings = [omp(x, atoms, sparsity) for x in data]

        for k in range(actual_k):
            contribution = _compute_atom_contribution(
                data,
                encodings,
                atoms,
                k,
                D,
            )
            new_atom = normalize(contribution)
            if norm(new_atom) > 0:
                atoms[k] = new_atom

    return atoms
