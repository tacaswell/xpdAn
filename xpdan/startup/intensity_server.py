from xpdan.vend.callbacks.zmq import *
from xpdan.pipelines.to_event_model import to_event_stream_with_ind
from xpdan.vend.callbacks.core import RunRouter, StripDepVar
from xpdconf.conf import glbl_dict
from shed.simple import *
from rapidz import Stream, zip as szip
import numpy as np


def run_server(
    prefix=None,
    outbound_proxy_address=glbl_dict["outbound_proxy_address"],
    inbound_proxy_address=glbl_dict["inbound_proxy_address"],
    _publisher=None,
    positions=(),
    stage="integration",
    x_name="q",
    y_name="mean",
):
    """Start up server for extracting single intensities

    Parameters
    ----------
    prefix : bytes or list of bytes, optional
        The Publisher channels to listen to. Defaults to
        ``[b"an", b"raw"]``
    outbound_proxy_address : str, optional
        The address and port of the zmq proxy. Defaults to
        ``glbl_dict["outbound_proxy_address"]``
    inbound_proxy_address : str, optional
        The inbound ip address for the ZMQ server. Defaults to the value
        from the global dict
    positions : list of float
        The positions to track
    stage : str
        The analysis stage to use for the data
    x_name : str
        The name of the pattern independent variable (``q`` or ``r`` for example)
    y_name : str
        The name of the pattern dependent variable (``mean`` or ``gr`` for example)

    Returns
    -------

    """
    if prefix is None:
        prefix = [b"an", b"raw"]

    rd = RemoteDispatcher(outbound_proxy_address, prefix=prefix)

    if _publisher is None:
        pub = Publisher(inbound_proxy_address, prefix=b"qoi")
    else:
        pub = _publisher

    source1 = Stream()
    source2 = Stream()

    x = SimpleFromEventStream("event", ("data", x_name), upstream=source1)
    iq = SimpleFromEventStream(
        "event", ("data", y_name), upstream=source1, principle=True
    )

    vals = [
        iq.combine_latest(
            x.map(lambda x, y: np.argmin(np.abs(x - y)), pos), emit_on=0
        ).starmap(lambda x, y: x[y])
        for pos in positions
    ]

    tes = SimpleToEventStream(
        szip(*vals),
        [f"peak_{x_name}={p}" for p in positions],
        analysis_stage="peaks",
    )

    z = move_to_first(source2.starmap(StripDepVar()))
    to_event_stream_with_ind(z, tes, publisher=pub)

    rr = RunRouter(
        [
            lambda x: lambda *y: source2.emit(y)
            if x.get("analysis_stage", "") == "raw"
            else None,
            lambda x: lambda *y: source1.emit(y)
            if x.get("analysis_stage", "") == stage
            else None,
        ]
    )
    rd.subscribe(rr)
    rd.start()


def run_main():
    import fire

    fire.Fire(run_server)


if __name__ == "__main__":
    run_main()
