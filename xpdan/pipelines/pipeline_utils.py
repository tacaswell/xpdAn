import os
from collections import Iterable
from pathlib import Path

from bluesky.callbacks import CallbackBase
from xpdan.dev_utils import _timestampstr


def if_dark(doc):
    return doc.get('dark_frame', False)


def if_query_results(n_hdrs):
    return n_hdrs > 0


def if_calibration(start):
    # print("detector cal tf ================================")
    # pprint(start)
    # print('detector_calibration_server_uid' in start)
    # return 'is_calibration' in start
    return 'detector_calibration_server_uid' in start


def if_not_calibration(doc):
    return 'is_calibration' not in doc and 'calibration_md' in doc
    # return 'calibration_client_uid' in doc
    # return 'calibration_server_uid' not in doc


def dark_template_func(timestamp, template):
    """Format template for dark images

    Parameters
    ----------
    timestamp: float
        The time in unix epoch
    template: str
        The string to be formatted

    Returns
    -------
    str:

    """
    d = {'human_timestamp': _timestampstr(timestamp), 'ext': '.tiff'}
    t = template.format(**d)
    os.makedirs(os.path.split(t)[0])
    return t


def templater1_func(doc, template):
    """format base string with data from experiment, sample_name,
    folder_tag"""
    d = {'sample_name': doc.get('sample_name', ''),
         'folder_tag': doc.get('folder_tag', '')}
    return template.format(**d)


def templater2_func(doc, template, aux=None, short_aux=None):
    """format with auxiliary and time"""
    if aux is None:
        aux = ['temperature', 'diff_x', 'diff_y', 'eurotherm']
    if short_aux is None:
        short_aux = ['temp', 'x', 'y', 'euro']
    aux_res = ['{}={}'.format(b, doc['data'].get(a, ''))
               for a, b in zip(aux, short_aux)]

    aux_res_str = '_'.join(aux_res)
    # Add a separator between timestamp and extras
    if aux_res_str:
        aux_res_str = '_' + aux_res_str
    return template.format(
        # Change to include name as well
        auxiliary=aux_res_str,
        human_timestamp=_timestampstr(doc['time']))


def templater3_func(template, analysis_stage='raw', ext='.tiff'):
    return Path(template.format(analysis_stage=analysis_stage,
                                ext=ext)).as_posix()


def clear_combine_latest(node, position=None):
    if position is None:
        position = range(len(node.last))
    elif not isinstance(position, Iterable):
        position = (position,)
    for p in position:
        node.last[p] = None
        node.missing.add(node.upstreams[p])


class Filler(CallbackBase):
    """Fill events without provenence"""

    def __init__(self, db):
        self.db = db
        self.descs = None

    def start(self, docs):
        self.descs = []
        return 'start', docs

    def descriptor(self, docs):
        self.descs.append(docs)
        return 'descriptor', docs

    def event(self, docs):
        d = next(self.db.fill_events([docs], self.descs))
        return 'event', d

    def stop(self, docs):
        return 'stop', docs


base_template = (''
                 '{base_folder}/{folder_prefix}/'
                 '{analysis_stage}/'
                 '{raw_start[sample_name]}_'
                 '{human_timestamp}_'
                 '[temp_{raw_event[data][temperature]:1.2f}'
                 '{raw_descriptor[data_keys][temperature][units]}]_'
                 '[dx_{raw_event[data][diff_x]:1.3f}'
                 '{raw_descriptor[data_keys][diff_x][units]}]_'
                 '[dy_{raw_event[data][diff_y]:1.3f}'
                 '{raw_descriptor[data_keys][diff_y][units]}]_'
                 '{raw_start[uid]:.6}_'
                 '{raw_event[seq_num]:04d}{ext}')
