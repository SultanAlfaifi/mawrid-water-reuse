"""Require concurrent unusual raw movement for local residual rescue.

A moving median can make a stationary reading appear far from its reference.
Only permit level/sustained rescue when the raw lag1/5 jump also exceeds its
normal-training q99.5 scale. This is a fixed development hypothesis, not a
physical fault classifier. Unknown jump is unavailable; ordinary movement
provides zero rescue evidence. Baseline availability remains unchanged.
"""
import numpy as np
JUMP_NORMAL_LIMIT=1.0

def departure_scores(components):
    out={k:np.asarray(v,float).copy() for k,v in components.items()}
    jump=out['jump']
    for key in ('level','sustained'):
        out[key][np.isfinite(jump)&(jump<=JUMP_NORMAL_LIMIT)]=0.
        out[key][~np.isfinite(jump)]=np.nan
    return out
