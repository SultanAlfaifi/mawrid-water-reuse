"""Batch-only replay of an earlier-selected, later-certified fixed policy."""
from ml.gecco_v7.runtime_delayed import predict_frame as delayed_frame


def predict_frame(bundle, frame, *, gap_samples=None):
    if bundle.get('version') != 'v7_hgb_temporally_certified_120s':
        raise ValueError('A matching temporally certified experiment bundle is required')
    return delayed_frame({**bundle, 'version': 'v7_hgb_corroborated_confirmation_120s'},
                         frame, gap_samples=gap_samples)
