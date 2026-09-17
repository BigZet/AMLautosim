"""Balance whole connected groups before fitting any model; preserve source data."""

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from scripts.aml_dataset import aml_population_author as author
from scripts.aml_dataset.aml_training import SPLITS
from scripts.audit_aml_history_population import file_hash, require


def split_dataset(source, output):
    require(not output.exists(), 'Output exists')
    audit = json.loads((source / 'audit.json').read_bytes())
    for name, digest in audit['artifact_hashes'].items():
        require(file_hash(source / name) == digest, 'Source artifact drift')
    frame = pd.read_csv(source / 'targets.csv')
    families = sorted(frame.route_family.unique())
    bands = ['low', 'grey', 'high']
    names = list(SPLITS)
    vectors, ids = [], []
    for gid, rows in frame.groupby('group_id'):
        ids.append(gid)
        vectors.append([len(rows)] + [sum(rows.band == b) for b in bands] +
                       [sum(rows.route_family == f) for f in families])
    vectors = np.asarray(vectors, dtype=float)
    desired = np.asarray(list(SPLITS.values()))[:, None] * vectors.sum(axis=0)
    current = np.zeros_like(desired)
    importance = np.r_[1., np.ones(3), np.full(len(families), .2)]
    assignment = {}
    for index in sorted(range(len(ids)), key=lambda i: (-vectors[i, 0], ids[i])):
        vector = vectors[index]
        changes = (((current + vector - desired) ** 2 - (current - desired) ** 2)
                   / np.maximum(desired, 1) * importance).sum(axis=1)
        chosen = int(np.argmin(changes))
        current[chosen] += vector
        assignment[ids[index]] = names[chosen]
    frame['split'] = frame.group_id.map(assignment)
    output.mkdir(parents=True)
    for name in audit['artifact_hashes']:
        if name != 'targets.csv':
            shutil.copyfile(source / name, output / name)
    frame.to_csv(output / 'targets.csv', index=False)
    audit['artifact_hashes']['targets.csv'] = file_hash(output / 'targets.csv')
    audit['source_hashes'][__file__] = file_hash(__file__)
    audit['split_counts'] = dict(Counter(frame.split))
    audit['split_revision'] = dict(
        source=str(source), source_audit_sha256=file_hash(source / 'audit.json'),
        reason='Old size-by-class strata disproportionately assigned large high-pattern components to training',
        method='Deterministic whole-group balancing by rows, target bands and route families; no model predictions',
        split_weights=SPLITS, model_fitted_before_revision=False,
    )
    (output / 'audit.json').write_bytes(author.json_bytes(audit))
    print(frame.groupby('split').band.value_counts().unstack(fill_value=0).to_string())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    split_dataset(args.source, args.output)
