import os
import time

import pytest
from rapidz import Stream
from rapidz.link import link

from xpdan.pipelines.save_tiff import pipeline_order


@pytest.mark.parametrize("exception", [True, False])
@pytest.mark.parametrize("background", [True, False])
def test_tiff_pipeline(
    exp_db, fast_tmp_dir, start_uid3, start_uid1, background, exception
):
    namespace = link(
        *pipeline_order, raw_source=Stream(stream_name="raw source"),
        db=exp_db
    )
    namespace["save_kwargs"].update({"base_folder": fast_tmp_dir})
    raw_source = namespace["raw_source"]

    t0 = time.time()
    if background:
        uid = start_uid1
    else:
        uid = -1

    for nd in exp_db[uid].documents():
        name, doc = nd
        if name == "start":
            if exception:
                doc["bt_wavelength"] = "bla"
            nd = (name, doc)
        try:
            raw_source.emit(nd)
        except ValueError:
            pass
    if background:
        name = "kapton"
    else:
        name = "Au"
    t1 = time.time()
    print(t1 - t0)
    n_events = len(list(exp_db[-1].events()))
    for root, dirs, files in os.walk(fast_tmp_dir):
        level = root.replace(fast_tmp_dir, "").count(os.sep)
        indent = " " * 4 * level
        print("{}{}/".format(indent, os.path.basename(root)))
        subindent = " " * 4 * (level + 1)
        for f in files:
            print("{}{}".format(subindent, f))
    print(os.listdir(fast_tmp_dir))
    print(os.listdir(os.path.join(fast_tmp_dir, name)))
    assert name in os.listdir(fast_tmp_dir)
    for f in ["dark_sub"]:
        assert f in os.listdir(os.path.join(fast_tmp_dir, name))
        assert len(os.listdir(os.path.join(fast_tmp_dir, name, f))) == n_events
    assert "{}_{:.6}.yaml".format(
        name, exp_db[uid].start["uid"][:6]
    ) in os.listdir(os.path.join(fast_tmp_dir, name, "meta"))
