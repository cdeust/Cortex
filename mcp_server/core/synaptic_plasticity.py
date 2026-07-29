"""Synaptic plasticity — public API facade.

Aggregates the three implementation modules into one import surface:

- ``synaptic_plasticity_stp`` — Tsodyks-Markram short-term plasticity
  (Tsodyks & Markram 1997, PNAS 94:719-723; Markram et al. 1998), Gaussian
  noise injection, and theta-phase gating (Hasselmo 2005). Leaf module,
  stdlib-only imports.
- ``synaptic_plasticity_hebbian`` — BCM LTP/LTD (Bienenstock, Cooper & Munro
  1982) and STDP (Bi & Poo 1998).
- ``synaptic_plasticity_stochastic`` — stochastic-release-gated Hebbian
  updates combining the two above.

This module holds no implementation. Until #233 the STP implementation lived
here and the two sibling modules imported it back, forming a cycle that made
``import mcp_server.core.synaptic_plasticity_hebbian`` (or ``_stochastic``)
fail outright in a fresh interpreter. Moving the implementation down into the
leaf ``synaptic_plasticity_stp`` makes every dependency point one way, so all
four modules import in any order.

Pure business logic — no I/O.
"""

from __future__ import annotations

from mcp_server.core.synaptic_plasticity_hebbian import (
    apply_hebbian_update,
    apply_stdp_batch,
    compute_bcm_phi,
    compute_ltd,
    compute_ltp,
    compute_stdp_update,
    update_bcm_threshold,
)
from mcp_server.core.synaptic_plasticity_stochastic import (
    apply_stochastic_hebbian_update,
)
from mcp_server.core.synaptic_plasticity_stp import (
    SynapticState,
    compute_effective_release_probability,
    compute_noisy_weight_update,
    phase_modulate_plasticity,
    stochastic_transmit,
    update_short_term_dynamics,
)

__all__ = [
    "SynapticState",
    "compute_effective_release_probability",
    "stochastic_transmit",
    "update_short_term_dynamics",
    "compute_noisy_weight_update",
    "phase_modulate_plasticity",
    "compute_bcm_phi",
    "compute_ltp",
    "compute_ltd",
    "update_bcm_threshold",
    "apply_hebbian_update",
    "compute_stdp_update",
    "apply_stdp_batch",
    "apply_stochastic_hebbian_update",
]
