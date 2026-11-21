"""Sample datasets for a first launch, so there is something to run straight away.

One set of synthetic Nasdaq stocks and one of synthetic CME futures, marked ``sample`` so
the Data page can remove them in one go. Building is slow, so it is split like any other
dataset: ``build_samples`` (worker thread, announces nothing) then ``commit_samples``.
"""
from __future__ import annotations

from ..core.data import DatasetInfo

SAMPLES = (
    ("synthetic_stocks", {"n_symbols": 20, "n_days": 60}, "Sample stocks (20 made-up Nasdaq names)"),
    ("synthetic_futures", {"n_days": 60}, "Sample futures (made-up MNQ on CME)"),
)


def build_samples(datasets) -> list[DatasetInfo]:
    out = []
    for source, params, name in SAMPLES:
        info = datasets.build(source, params, name)
        info.sample = True
        info.notes = (info.notes + " " if info.notes else "") + "A sample to try things with; no real edge."
        out.append(info)
    return out


def commit_samples(datasets, infos: list[DatasetInfo]) -> list[DatasetInfo]:
    return [datasets.commit(i) for i in infos]


def add_samples(datasets) -> list[DatasetInfo]:
    return commit_samples(datasets, build_samples(datasets))


def remove_samples(datasets) -> list[str]:
    """Remove every sample no strategy uses. Returns the ids removed."""
    gone = []
    for info in list(datasets.infos()):
        if info.sample and not info.used_by and not datasets.dependents(info.id):
            datasets.remove(info.id)
            gone.append(info.id)
    return gone
