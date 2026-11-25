"""Evidence helper (Stage 4 slice 1): duplicate a factory into two
independent plants by suffixing every entity that a plan writes to.
"""

from brain_core.records.models import Factory


def two_plant_factory(factory: Factory) -> Factory:
    """factory + a renamed copy: two proven-independent cells."""
    f = factory
    sfx = "@P2"
    items2 = [i.model_copy(update={"name": i.name + sfx})
              for i in f.items]
    mats2 = [m.model_copy(update={"name": m.name + sfx})
             for m in f.setup_matrices]
    for m_old, m_new in zip(f.setup_matrices, mats2):
        m_new.rules = [r.model_copy(update={
            "from_setup": r.from_setup + sfx,
            "to_setup": r.to_setup + sfx}) for r in m_old.rules]
    res2 = [r.model_copy(update={
        "name": r.name + sfx,
        "setup_matrix": (r.setup_matrix + sfx
                         if r.setup_matrix else None)})
        for r in f.resources]
    ops2 = []
    for op in f.operations:
        ops2.append(op.model_copy(update={
            "name": op.name + sfx,
            "item": (op.item + sfx if op.item else None),
            "materials": [m.model_copy(update={"item": m.item + sfx})
                          for m in op.materials],
            "loads": [ld.model_copy(update={
                "resource": ld.resource + sfx,
                "setup": (ld.setup + sfx if ld.setup else None)})
                for ld in op.loads]}))
    buf2 = [b.model_copy(update={"item": b.item + sfx})
            for b in f.buffers]
    dem2 = [d.model_copy(update={"name": d.name + sfx,
                                 "item": d.item + sfx})
            for d in f.demands]
    return Factory(
        locations=f.locations,
        items=list(f.items) + items2,
        calendars=f.calendars,
        setup_matrices=list(f.setup_matrices) + mats2,
        resources=list(f.resources) + res2,
        operations=list(f.operations) + ops2,
        buffers=list(f.buffers) + buf2,
        demands=list(f.demands) + dem2)
