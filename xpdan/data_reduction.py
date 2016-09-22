#!/usr/bin/env python
##############################################################################
#
# xpdacq            by Billinge Group
#                   Simon J. L. Billinge sb2896@columbia.edu
#                   (c) 2016 trustees of Columbia University in the City of
#                        New York.
#                   All rights reserved
#
# File coded by:    Timothy Liu
#
# See AUTHORS.txt for a list of people who contributed.
# See LICENSE.txt for license information.
#
##############################################################################
import os
import warnings
import datetime
import yaml
import numpy as np
import tifffile as tif
import matplotlib as plt
from time import strftime
from unittest.mock import MagicMock

from .glbl import an_glbl
from .tools import mask_img

from pyFAI.azimuthalIntegrator import AzimuthalIntegrator
from itertools import islice

# top definition for minimal impacts on the code 
from databroker.databroker import get_table

w_dir = os.path.join(an_glbl.home, 'tiff_base')
W_DIR = w_dir  # in case of crashes in old codes


class DataReduction:
    """ class that handle operations on images from databroker header

        Note: not a callback
    """

    def __init__(self, exp_db=an_glbl.exp_db, image_field=None):
        # for file name 
        self.fields = ['sample_name', 'sp_type', 'sp_requested_exposure']
        self.labels = ['dark_frame']
        self.data_fields = ['temperature']
        self.root_dir_name = 'sample_name'
        self.exp_db = exp_db
        if image_field is None:
            self.image_field = an_glbl.det_image_field

    def _feature_gen(self, event):
        """ generate a human readable file name.

        file name is generated by metadata information in event
        run_start
        """
        feature_list = []
        run_start = event.descriptor['run_start']
        uid = run_start['uid'][:6]
        # get special label
        for el in self.labels:
            label = run_start.get(el, None)
            if label is not None:
                feature_list.append(str(label))
            else:
                pass
        # get fields
        for key in self.fields:
            el = str(run_start.get(key, None))
            if el is not None:
                # truncate string length
                if len(el) > 12:
                    value = el[:12]
                # clear space
                feature = _clean_info(el)
                feature_list.append(feature)
            else:
                pass
        # get data fields
        for key in self.data_fields:
            val = event['data'].get(key, None)
            if el is not None:
                feature = "{}={}".format(key, val)
                feature_list.append(feature)
            else:
                pass
        # get uid
        feature_list.append(uid)
        return "_".join(feature_list)

    def pull_dark(self, header):
        dark_uid = header.start.get(an_glbl.dark_field_key, None)
        if dark_uid is None:
            print("INFO: no dark frame is associated in this header, "
                  "subrraction will not be processed")
            return None
        else:
            dark_search = {'group': 'XPD', 'uid': dark_uid}
            dark_header = self.exp_db(**dark_search)
            dark_img = np.asarray(self.exp_db.get_images(dark_header,
                                             self.image_field)).squeeze()
        return dark_img, dark_header[0].start.time

    def _dark_sub(self, event, dark_img):
        """ priviate method operates on event level """
        dark_sub = False
        img = event['data'][self.image_field]
        if dark_img is not None and isinstance(dark_img, np.ndarray):
            dark_sub = True
            img -= dark_img
        ind = event['seq_num']
        event_timestamp = event['timestamps'][self.image_field]
        return img, event_timestamp, ind, dark_sub

    def dark_sub(self, header):
        """ public method operates on header level """
        img_list = []
        timestamp_list = []
        dark_img, dark_time_stamp = self.pull_dark(header)
        for ev in self.exp_db.get_events(header, fill=True):
            sub_img, timestamp, ind, dark_sub = self._dark_sub(ev, dark_img)
            img_list.append(sub_img)
            timestamp_list.append(timestamp)
        return img_list, timestamp_list, dark_img, header.start

    def _file_name(self, event, event_timestamp, ind):
        """ priviate method operates on event level """
        f_name = self._feature_gen(event)
        f_name = '_'.join([_timestampstr(event_timestamp),
                           f_name])
        f_name = '{}_{:04d}.tif'.format(f_name, ind)
        return f_name


# init
xpd_data_proc = DataReduction()
ai = AzimuthalIntegrator()
geo = Geometry()

### analysis function operates at header level ###
def _prepare_header_list(headers):
    if not isinstance(headers, list):
        # still do it in two steps, easier to read
        header_list = list()
        header_list.append(headers)
    else:
        header_list = headers
    return header_list


def _load_config():
    with open(
            os.path.join(an_glbl.config_base, an_glbl.calib_config_name)) as f:
        config_dict = yaml.load(f)
    return config_dict


def _npt_cal(config_dict, total_shape=(2048, 2048)):
    """ config_dict should be a PyFAI calibration dict """
    x_0, y_0 = (config_dict['centerX'], config_dict['centerY'])
    center_len = np.hypot(x_0, y_0)
    # FIXME : use hardwired shape now, use direct info later
    x_total, y_total = total_shape
    total_len = np.hypot(x_total, y_total)
    # FIXME : use the longest diagonal distance. Optimal value might have
    # to do with grid of Fourier transform. Need to revisit it later
    dist = max(total_len, total_len - center_len)
    return dist


def integrate_and_save(headers, auto_dark=True,
                       polarization_factor=0.99,
                       auto_mask=True, mask_dict=None,
                       save_image=True, root_dir=None,
                       config_dict=None, handler=xpd_data_proc, **kwargs):
    """ integrate and save dark subtracted images for given list of headers

        Parameters
        ----------
        headers : list
            a list of databroker.header objects
        auto_dark : bool, optional
            option to turn on/off dark subtraction functionality
        polarization_factor : float, optional
            polarization correction factor, ranged from -1(vertical) to 
            +1 (horizontal). default is 0.99. set to None for no
            correction.
        auto_mask : bool, optional
            turn on/off of automask functionality. default is True
        mask_dict : dict, optional
            dictionary stores options for automasking functionality. 
            default is defined by an_glbl.auto_mask_dict. 
            Please refer to documentation for more details
        save_image : bool, optional
            option to save dark subtracted images. images will be 
            saved to the same directory of chi files. default is True.
        root_dir : str, optional
            path of chi files that are going to be saved. default is 
            xpdUser/userAnalysis/
        config_dict : dict, optional
            dictionary stores integration parameters of pyFAI azimuthal 
            integrator. default is the most recent parameters saved in 
            xpdUser/conifg_base
        handler : instance of class, optional
            instance of class that handles data process, don't change it 
            unless needed.
        kwargs :
            addtional keywords to overwrite integration behavior. Please
            refer to pyFAI.azimuthalIntegrator.AzimuthalIntegrator for
            more information

    Note
    ----
    complete docstring of masking functionality could be find in
    ``mask_img``

    See also
    --------
    xpdan.tools.mask_img
    pyFAI.azimuthalIntegrator.AzimuthalIntegrator
    """
    # normalize list
    header_list = _prepare_header_list(headers)

    # config_dict
    if config_dict is None:
        config_dict = _load_config() # default dict 

    # setting up geometry
    ai.setPyFAI(**config_dict)
    npt = _npt_cal(config_dict)

    total_rv_list_Q = []
    total_rv_list_2theta = []

    # iterate over header
    for header in header_list:
        root = header.start.get(handler.root_dir_name, None)
        if root is not None:
            root_dir = os.path.join(W_DIR, root)
            os.makedirs(root_dir, exist_ok=True)
        else:
            root_dir = W_DIR
        header_rv_list_Q = []
        header_rv_list_2theta = []
        # dark logic
        dark_img = None
        if auto_dark:
            dark_img, dark_time = handler.pull_dark(header)
        for event in handler.exp_db.get_events(header, fill=True):
            # dark subtraction
            img, event_timestamp, ind, dark_sub = handler._dark_sub(event,
                                                                    dark_img)
            # basic file name
            f_name = handler._file_name(event, event_timestamp, ind)
            if dark_sub:
                f_name = 'sub_' + f_name

            # masking logic
            mask = None
            if auto_mask:
                print("INFO: mask your image: {}".format(f_name))
                f_name = 'masked_' + f_name
                if mask_dict is None:
                    mask_dict = an_glbl.mask_dict
                mask = mask_img(img, geo, **mask_dict)

            # integration logic
            stem, ext = os.path.splitext(f_name)
            chi_name_Q = stem + '_Q_' + '.chi' # q_nm^-1
            print("INFO: integrating image: {}".format(f_name))
            # Q-integration
            chi_fn = os.path.join(root_dir, chi_name_Q)
            rv_Q = ai.integrate1d(img, npt, filename=chi_fn, mask=mask,
                                  polarization_factor=polarization_factor,
                                  unit="q_nm^-1", **kwargs)
            print("INFO: save chi file: {}".format(chi_name_Q))
            # 2theta-integration
            chi_fn = os.path.join(root_dir, chi_name_2th)
            rv_2th = ai.integrate1d(img, npt, filename=chi_fn, mask=mask,
                                    polarization_factor=polarization_factor,
                                    unit="2th_deg", **kwargs)
            print("INFO: save chi file: {}".format(chi_name_2th))
            # return integration results
            header_rv_list_Q.append(rv_Q)
            header_rv_list_2theta.append(rv_2th)

            # save image logic
            w_name = os.path.join(root_dir, f_name)
            if save_image:
                tif.imsave(w_name, img)
                if os.path.isfile(w_name):
                    print('image "%s" has been saved at "%s"' %
                        (f_name, root_dir))
                else:
                    print('Sorry, something went wrong with your tif saving')
                    return

        # each header generate  a list of rv
        total_rv_list_Q.append(header_rv_list_Q)
        total_rv_list_2theta.append(header_rv_list_2theta)

    print("INFO: chi/image files are saved at {}".format(root_dir))
    return total_rv_list_Q, total_rv_list_2theta


def integrate_and_save_last(dark_sub=True, polarization_factor=0.99,
                            auto_mask=True, mask_dict=None,
                            save_image=True, root_dir=None,
                            config_dict=None, handler=xpd_data_proc, **kwargs):
    """ integrate and save dark subtracted images for given list of headers

        Parameters
        ----------
        dark_sub : bool, optional
            option to turn on/off dark subtraction functionality
        polarization_factor : float, optional
            polarization correction factor, ranged from -1(vertical) to 
            +1 (horizontal). default is 0.99. set to None for no
            correction.
        auto_mask : bool, optional
            turn on/off of automask functionality. default is True
        mask_dict : dict, optional
            dictionary stores options for automasking functionality. 
            default is defined by an_glbl.auto_mask_dict. 
            Please refer to documentation for more details.
        save_image : bool, optional
            option to save dark subtracted images. images will be 
            saved to the same directory of chi files. default is True.
        root_dir : str, optional
            path of chi files that are going to be saved. default is 
            xpdUser/userAnalysis/
        config_dict : dict, optional
            dictionary stores integration parameters of pyFAI azimuthal 
            integrator. default is the most recent parameters saved in 
            xpdUser/conifg_base
        handler : instance of class, optional
            instance of class that handles data process, don't change it 
            unless needed.
        kwargs :
            addtional keywords to overwrite integration behavior. Please
            refer to pyFAI.azimuthalIntegrator.AzimuthalIntegrator for
            more information

    Note
    ----
    complete docstring of masking functionality could be find in
    ``mask_img``

    See also
    --------
    xpdan.tools.mask_img
    pyFAI.azimuthalIntegrator.AzimuthalIntegrator
    """
    integrate_and_save(db[-1], auto_dark=auto_dark,
                       polarization_factor=polarization_factor,
                       auto_mask=auto_mask, mask_dict=mask_dict,
                       save_image=save_image,
                       root_dir=root_dir,
                       config_dict=config_dict,
                       handler=handler)


def save_tiff(headers, dark_sub=True, max_count=None, dryrun=False,
              handler=xpd_data_proc):
    """ save images obtained from dataBroker as tiff format files.

    Parameters
    ----------
    headers : list
        a list of header objects obtained from a query to dataBroker.

    dark_subtraction : bool, optional
        Default is True, which allows dark/background subtraction to 
        be done before saving each image. If header doesn't contain
        necessary information to perform dark subtraction, uncorrected
        image will be saved.

    max_count : int, optional
        The maximum number of events to process per-run.  This can be
        useful to 'preview' an export or if there are corrupted files
        in the data stream (ex from the IOC crashing during data
        acquisition).

    dryrun : bool, optional
        if set to True, file won't be saved. default is False

    handler : instance of class
        instance of class that handles data process, don't change it
        unless needed.
    """
    # normalize list
    header_list = _prepare_header_list(headers)

    for header in header_list:
        # create root_dir
        root = header.start.get(handler.root_dir_name, None)
        if root is not None:
            root_dir = os.path.join(W_DIR, root)
            os.makedirs(root_dir, exist_ok=True)
        else:
            root_dir = W_DIR
        # dark logic
        dark_img = None
        if dark_sub:
            dark_img, dark_time = handler.pull_dark(header)
        # event
        for event in handler.exp_db.get_events(header, fill=True):
            img, event_timestamp, ind, dark_sub = handler._dark_sub(event,
                                                                    dark_img)
            f_name = handler._file_name(event, event_timestamp, ind)
            if dark_sub:
                f_name = 'sub_' + f_name
            # save tif
            w_name = os.path.join(root_dir, f_name)
            if not dryrun:
                tif.imsave(w_name, img)
                if os.path.isfile(w_name):
                    print('image "%s" has been saved at "%s"' %
                          (f_name, root_dir))
                else:
                    print('Sorry, something went wrong with your tif saving')
                    return
            # dryrun : print
            else:
                print("dryrun: image {} has been saved at {}"
                      .format(f_name, root_dir))
            if max_count is not None and ind >= max_count:
                # break the loop if max_count reached, move to next header
                break

        # save run_start
        stem, ext = os.path.splitext(w_name)
        config_name = w_name.replace(ext, '.yaml')
        with open(config_name, 'w') as f:
            yaml.dump(header.start, f) # save all md in start

    print(" *** {} *** ".format('Saving process finished'))


def save_last_tiff(dark_sub=True, max_count=None, dryrun=False,
                   handler=xpd_data_proc):
    """ save images from the most recent scan as tiff format files.

    Parameters
    ----------
    dark_subtraction : bool, optional
        Default is True, which allows dark/background subtraction to 
        be done before saving each image. If header doesn't contain
        necessary information to perform dark subtraction, uncorrected
        image will be saved.

    max_count : int, optional
        The maximum number of events to process per-run.  This can be
        useful to 'preview' an export or if ithere are corrupted files
        in the data stream (ex from the IOC crashing during data acquisition).

    dryrun : bool, optional
        if set to True, file won't be saved. default is False

    handler : instance of class
        instance of class that handles data process, don't change it
        unless needed.
    """

    save_tiff(handler.exp_db[-1], dark_sub, max_count, dryrun,
              handler=handler)


def sum_images(header, idxs_list=None, handler=xpd_data_proc):
    """Sum images in a header

    Sum the images in a header according to the idxs_list

    Parameters
    ----------
    header: mds.header
        The run header to be summed
    idxs_list: list of lists and tuple, optional
        The list of lists and tuples which specify the images to be summed.
        If None, sum all the images in the run. Defaults to None.
    handler : instance of class
        instance of class that handles data process, don't change it
        unless needed.
    Returns
    -------
    list:
        The list of summed images

    >>> hdr = db[-1]
    >>> total_imgs = sum_images(hdr) # Sum all the images
    >>> assert len(total_imgs) == 1
    >>> total_imgs = sum_images(hdr, [1, 2, 3])
    >>> assert len(total_imgs) == 1
    >>> total_imgs = sum_images(hdr, [[1, 2, 3], (5,10)])
    >>> assert len(total_imgs) == 2
    """
    if idxs_list is None:
        total_img = None
        for event in handler.exp_db.get_events(header, fill=True):
            if total_img is None:
                total_img = event['data'][handler.image_field]
            else:
                total_img += event['data'][handler.image_field]
        return [total_img]
    else:
        total_img_list = []
        # If we only have one list make it into a list of lists
        if not all(isinstance(e1, list) or isinstance(e1, tuple) for e1 in
                   idxs_list):
            idxs_list = [idxs_list]
        for idxs in idxs_list:
            total_img = None
            if isinstance(idxs, tuple):
                events = handler.exp_db.get_events(header, fill=True)
                for idx in range(idxs[0], idxs[1]):
                    if total_img is None:
                        total_img = next(islice(events, idx))['data'][
                            handler.image_field]
                    else:
                        total_img += next(islice(events, idx))['data'][
                            handler.image_field]
            else:
                events = handler.exp_db.get_events(header, fill=True)
                total_img = None
                for idx in idxs:
                    if total_img is None:
                        total_img = next(islice(events, idx))['data'][
                            handler.image_field]
                    else:
                        total_img += next(islice(events, idx))['data'][
                            handler.image_field]
            total_img_list.append(total_img)
        return total_img_list
