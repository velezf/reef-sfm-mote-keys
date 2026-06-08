# -*- coding: utf-8 -*-
"""
------------------------------------------------------------------------------
Metashape Image Alignment and Error Reduction Script v2
for Agisoft Metashape 2.0.x

This script automates the Agisoft Metashape image alignment and error
reduction. The default arguments in the script are set to follow the workflow
described in U.S. Geological Survey Open-File Report 2021-1039 (Over et al. (2021))
The error reduction technique and gradual selection values were developed
with the goal to maintain the accuracies of the traditional photogrammetric
process with newer techniques supported by structure from motion (SfM) based
software.

The script allows users to align imagery and apply different gradual selection
filters to sparse point clouds. Each filter can either be applied once, to
select and delete a user-specified portion of sparse points, or it can be applied
iteratively to select and delete a portion of sparse points until a user-specified
filter level is achieved. Camera optimization is performed between each iteration
to improve the camera lens model using the newly filtered subset of higher
quality sparse point matches.

The default workflow applies the Reconstruction Uncertainty (Ru) and Projection
Accuracy (Pa) filters once each, to select 50% of the sparse points.  Camera
optimization is performed after each filter is applied. Reprojection Error (Re)
is applied iteratively, such that only 10% of the points are selected during an
iteration. Camera optimization is performed after each iteration, and iterations
continue until a user-specified filter level is achieved. After the final Re
filter, camera optimization is performed a final time with "fit additional
corrections" enabled.

Although the default iteration behavior and filter levels are defined
for each filter in the workflow described in Over et al. (2021), the user
can deviate from this workflow using command line arguments or by changing the
hardcoded ‘defaults’ object at the beginning of the script (lines 246-324). For
instance, if the user wishes to ensure that all remaining sparse points satisfy
a specific Reconstruction Uncertainty (Ru) or Projection Accuracy (Pa) level,
these filters can be run iteratively to delete points until the required filter
level is met. The default workflow performed by this script, and the suggested
filter levels may not be appropriate for all imagery and projects; use caution
if accepting these defaults.

For more information about the default workflow and suggested parameters,
please see:

    Over, J.R., A.C. Ritchie, C. Kranenburg, J.A. Brown, D.D. Buscombe,
    T. Noble, C.R. Sherwood, J. Warrick, and P.A. Wernette. (2021) Processing
    coastal imagery with Agisoft Metashape Professional Edition, version
    1.6—Structure from motion workflow documentation: U.S. Geological Survey
    Open-File Report 2021-1039, x p. www.doi.org/10.3133/ofr20211039.

------------------------------------------------------------------------------
usage:
Align_RuPaRe_v2.py [-h]
                    Display help message, list of args.
                [-chunk [str name of chunk]]
                    Initial chunk to process. Optional. [Default=active chunk]
                [-align]
                    Perform image alignment.
                        Optional alignment sub-arguments:
                            [-al_accuracy [highest, high, medium, low, lowest]]
                                Alignment accuracy. [Default=high]
                            [-al_kplim [float]]
                                Alignment keypoint limit. [Default=60,000]
                            [-al_tplim [float]]
                                Alignment tiepoint limit. [Default=0]
                            [-al_generic [bool]]
                                Alignment generic preselection. [Default=True]
                            [-al_reference [bool]]
                                Alignment reference preselection. [Default=True]
                            [-al_reference_mode [source, estimated, sequential]]
                                Alignment reference preselection mode. [Default=source]
                            [-al_cam_param [space or comma delim list of str (ex: f cx cy k1 k2)]
                                Camera optimization lens params.
                                        [Default= f, cx, cy, k1, k2, k3, p1, p2]
                            [-al_masktiepoints]
                                Mask tie points. [Default=False]
                            [-al_maskkeypoints]
                                Mask key points. [Default=False]
                [-ru]
                    Perform reconstruction uncertainty (Ru) gradual selection iterations.
                        Optional Ru sub-arguments:
                            [-ru_level [float]]
                                Ru gradual selection filter level [Default=10]
                            [-ru_cam_param [space or comma delim list of str (ex: f cx cy k1 k2)]
                                Camera optimization lens params.
                                        [Default= f, cx, cy, k1, k2, k3, p1, p2]
                        --- CHANGING THE -RU ARGUMENTS BELOW WILL DEVIATE FROM THE OFR 2021-1039 WORKFLOW ---
                            [-ru_iterate_to_ru_level [bool]]
                                Optionally iterate Ru gradual selection and sparse point
                                deletion until -ru_level is reached. If False, Ru gradual selection
                                will be run once to select a percentage of points
                                equal to -ru_max_percentage_delete; final Ru value may be higher than
                                value set by -ru_level [Default=False (filter will run once)]
                            [-ru_max_percentage_delete [float 0-1]]
                                Maximum percentage [0-1] of points to select and delete
                                during one iteration [Default=0.5]
                            [-ru_increment]
                                Ru gradual selection value to use for incremental selection
                                of points for deletion. Smaller values result in increased
                                script run time. [Default=0.1]
                [-pa]
                    Perform projection accuracy (Pa) gradual selection iterations.
                        Optional Pa sub-arguments:
                            [-pa_level [float]]
                                Pa gradual selection filter level [Default=3]
                            [-pa_cam_param [space or comma delim list of str (ex: f cx cy k1 k2)]
                                Camera optimization lens params.
                                        [Default= f, cx, cy, k1, k2, k3, p1, p2]
                        --- CHANGING THE -PA ARGUMENTS BELOW WILL DEVIATE FROM THE OFR 2021-1039 WORKFLOW ---
                            [-pa_iterate_to_pa_level [bool]]
                                Optionally iterate Pa gradual selection and sparse point
                                deletion until -pa_level is reached. If False, Pa gradual selection
                                will be run once to select a percentage of points
                                equal to -pa_max_percentage_delete; final Pa value may be higher than
                                value set by -Pa_level [Default=False (filter will run once)]
                            [-pa_max_percentage_delete [float 0-1]]
                                Maximum percentage [0-1] of points to select and delete
                                during one iteration [Default=0.5]
                            [-pa_increment]
                                Pa gradual selection value to use for incremental selection
                                of points for deletion. Smaller values result in increased
                                script run time. [Default=0.1]
                [-re]
                    Perform reprojection error (Re) gradual selection iterations.
                        Optional Re sub-arguments:
                            [-re_level [float]]
                                Re gradual selection filter level [Default=0.3]
                            [-re_cam_param [space or comma delim list of str (ex: f cx cy k1 k2)]
                                Camera optimization lens params.
                                        [Default= f, cx, cy, k1, k2, k3, p1, p2]
                        --- CHANGING THE -RE ARGUMENTS BELOW WILL DEVIATE FROM THE OFR 2021-1039 WORKFLOW ---
                            [-re_adapt_cam [bool]
                                Adjust camera opt. lens params based on Re level [Default=True]
                            [-re_adapt_level [float]]
                                Re level at which to add additional lens params. [Default=0.3]
                            [-re_adapt_cam_param [space or comma delim list of str (ex: k4, b1, b2)]
                                Additional lens params to add
                                        [Default, when enabled= k4, b1, b2]
                            [-re_fit_additional_corr [bool]]
                                Option to enable "Fit Additional Parameters" in camera optimization
                                        [Default=True]
                            [-re_final_tie_point_accuracy [float]]
                                Tie point accuracy set to this value during final camera optimization
                                after Re filter [Default = 0.3]
                            [-re_max_percentage_delete [float 0-1]]
                                Maximum percentage [0-1] of points to select and delete
                                during one iteration [Default=0.1]
                            [-re_increment]
                                Re gradual selection value to use for incremental selection
                                of points for deletion. Smaller values result in increased
                                script run time. [Default=0.01]
                            [-re_early_stop [bool]]
                                Option to stop Re early to prevent excessive iterations.
                                If no additional arguments called, a default minimum number of
                                iterations (-re_early_stop_min_iterations) will be performed , then iterations will
                                be stopped once Re level is within a set range (-re_early_stop_variance) of
                                target -re_level. [default=False]
                            [-re_early_stop_max_iterations [int]]
                                Minimum number of Re iterations to perform before allowing early stop [default=5]
                            [-re_early_stop_variance [float]]
                                Allowed variance from target rmse(-re_level) for activation of Re early stop [default=0.005]
                [-log [str name optional, otherwise Metashape proj. name used]]
                    Create optional processing log file. [Default=no log file]
                        (if -log provided with no arg, log will be named using Metashape proj. name)
                [-compute_rmse [bool]]
                    Option to enable/disable computation of RMSE for each chunk. Can be computationally intensive for large
                    projects [Default=True].
------------------------------------------------------------------------------
Script begins on chunk designated by optional '-chunk' argument.  If no chunk is
designated, the currently active chunk is used. Initial chunk is copied to a new
chunk and given a suffix of '_Align', '_RuX', '_PaX', or '_ReX' (where X is the
gradual selection filter level). Each operation creates a new chunk.

defaults:
    -chunk     active chunk

    -align     keypointlimit: 60000
               tiepointlimit: 0
               accuracy: high
               generic_preselection: True
               reference_preselection: True
               reference_preselection_mode: source
               camera optimization lens param: f, cx, cy, k1, k2, k3, p1, p2
               mask tie points: False
               mask key points: False

    -ru        Reconstruction Uncertainty level: 10.0
               camera optimization lens param: f, cx, cy, k1, k2, k3, p1, p2
               Iterate to Reconstruction Uncertainty level: False (filter will be run once to
                                                                   select and delete 50% of points
                                                                   (set with -ru_max_percentage_delete))
               Max. percentage deleted in iteration: 50%
               Incremental gradual selection value: 0.1

    -pa        Projection Accuracy level: 3.0
               camera optimization lens param: f, cx, cy, k1, k2, k3, p1, p2
               Iterate to Project Accuracy level: False (filter will be run once to
                                                         select and delete 50% of points
                                                         (set with -pa_max_percentage_delete))
               Max. percentage deleted in iteration: 50%
               Incremental gradual selection value: 0.1

    -re        Reprojection Error level: 0.3
               initial camera optimization lens param: f, cx, cy, k1, k2, k3, p1, p2
               camera optimization lens params adjusted when Re < 1 pixel
               adjusted camera optimization lens param: f, cx, cy, k1, k2, k3, p1, p2
               Iterate to Reprojection Error level: True, not configurable by user (filter will iterate and
                                                                            delete 10% of points at a time,
                                                                            (set with -re_max_precentage_delete))
               Max. percentage deleted in iteration: 10%
               Incremental gradual selection value: 0.01
               Tie point accuracy: Set to 1 during Re gradual selection iterations, then set to 0.3 during final camera
                       optimization.
               Fit additional corrections: Enabled during final camera optimization, after the last Re gradual selection filter has
                            completed.
               Re early stop: False
               Re early stop minimum iterations: 5 (only if Re early stop enabled)
               Re early stop rmse variance: 0.005 (only if Re early stop enabled)

    -log       Output processing log file name: XXXXX_ProcessingLog.txt (XXXXX = Metashape project name)
               (Log file name is optional. If not specified, then logs will be generated with the default schema)

    -compute_rmse: True

@authors:
This script was developed at the United States Geological Survey,
Pacific Coastal and Marine Science Center, Santa Cruz, CA
(https://walrus.wr.usgs.gov/).

    Joshua Logan 
    Phillipe Wernette 
    Andy Ritchie 

------------------------------------------------------------------------------
"""

import Metashape
import os
import sys
from datetime import datetime
import argparse
import copy as cp
import math

class Args():
    def __init__(self):
        """ Simple class to hold default arguments """
        # ==================== DEFAULT ARGUMENTS BELOW===========================================

        # Defaults can be changed below, but will be overridden at execution using any
        # command line arguments supplied by the user.

        # ------------Chunk defaults -------------------------------------------------------
        self.initial_chunk = 'active'           # Name of first chunk to operate on ('active' = active chunk)

        # ------------Alignment defaults -------------------------------------------------------
        self.align = False                      # run image alignment
        self.align_accuracy = 'high'            # image alignment accuracy (must be: 'highest', 'high', 'medium', 'low', 'lowest'
        self.keypointlimit = 60000              # alignment keypointlimit (0 = unlimited)
        self.tiepointlimit = 0                  # alignment tiepointlimit (0 = unlimited)
        self.gen_preselect = True               # alignment generic preselection
        self.ref_preselect = True               # alignment reference preselection
        self.ref_preselect_option = 'Source'    # alignment reference preselection options:  'Source',
        # alignment camera optimization parameters
        self.al_cam_opt_param = ['f','cx','cy','k1','k2','k3','p1','p2']
        self.al_masktiepoints = False
        self.al_maskkeypoints = False

        # ------------Reconstruction Uncertainty (ru) defaults ---------------------------------
        self.ru = False                         # run ru gradual selection filter
        self.ru_filt_level = 10                 # ru gradual selection filter level (default=10, optimum value: [10 - 15])
        # ru camera optimization parameters
        self.ru_cam_opt_param = ['f','cx','cy','k1','k2','k3','p1','p2']
        # Iterate Ru filter until Ru level achieved, or run once to select percentage of points equal to ru_cutoff
        self.ru_iterate_to_ru_level = False     # For workflow v2 = False, for workflow v1 = True [default=False]

        # ------------Projection Accuracy (pa) defaults ---------------------------------------
        self.pa = False                         # run pa gradual selection filter
        self.pa_filt_level = 3                  # pa gradual selection filter level (default=3, optimum value: [2-4])
        # pa camera optimization parameters
        self.pa_cam_opt_param = ['f','cx','cy','k1','k2','k3','p1','p2']
        # Iterate Pa filter until Pa level achieved, or run once to select percentage of points equal to pa_cutoff
        self.pa_iterate_to_pa_level = False     # For workflow v2 = False, for workflow v1 = True [default=False]

        # ------------Reprojection Error (re) defaults -----------------------------------------
        self.re = False                         # run re gradual selection filter iterations
        self.re_filt_level = 0.3                # re gradual selection filter level (default=0.3, optimum value: [0.3])
        self.re_final_tie_point_accuracy = 0.3  # tie point accuracy for final camera optimization after Re filter complete (default=0.3)
        # re camera optimization parameters
        self.re_cam_opt_param = ['f','cx','cy','k1','k2','k3','p1','p2']
        self.re_fit_additional_corr = True
        # adjust camera optimization parameters when Re level is below threshold (initially enabled in workflow v1 (legacy),
        # disabled in workflow v2 but functionality retained)
        self.re_adapt = False                   # enable adaptive camera opt params (workflow v2 default=False; v1 default=True)
        self.re_adapt_level = 1                 # Re level below which to adjust camera opt params (default=1)
        # camera optimization parameters to enable after Re is below re_adapt_level. These are enabled and added to initial re_cam_opt_param
        self.re_adapt_add_cam_param = ['k4','b1','b2']  # all disabled by default (see OFR for more details)
        # early stop parameters (use to stop Re after a certain number of iterations, and within a set threshold of target Re filter level)
        self.re_early_stop = False              # enable early_stop (default=False)
        self.re_early_stop_min_iterations = 5       # minimum number of iterations to before early stop
        self.re_early_stop_variance = 0.005    # allowed variance from target rmse for early stop

        # ------------Process logging defaults ------------------------------------------------
        self.log = True
        # logfile name. Set to 'default.txt' to have output file named X_ProcessingLog.txt, where X=name of Metashape project
        self.proclogname = 'default.txt'

        # ------------Compute RMSE default ---------------------------------------------------
        self.compute_rmse = True

        # ------------ru, pa, re iteration defaults -------------------------------------------
        """
        Read and make sure you understand the published OFR workflow referenced
        on lines 46-50 before changing the following values. Changing ru_increment,
        pa_increment, and/or re_increment values may result in infinite loops.
        """
        self.ru_cutoff = 0.50                   # percentage of points removed in single Ru iteration [0.50]
        self.pa_cutoff = 0.50                   # percentage of points removed in single Pa iteration [0.50]
        self.re_cutoff = 0.10                   # percentage of points removed in single Re iteration [0.10]
        # Changing these values may result in infinite loops
        self.ru_increment = 0.1                 # increment by which Ru filter advanced when finding Ru level to select ru_cutoff percentage [0.1]
        self.pa_increment = 0.1                 # increment by which Pa filter advanced when finding Pa level to select pa_cutoff percentage [0.1]
        self.re_increment = 0.01                # increment by which Re filter advanced when finding Re level to select re_cutoff percentage [0.01]


# ==================== FUNCTIONS BELOW===========================================
def compute_RMSE(chunk):
    """
    Compute the chunk RMSE from all active cameras with valid transform and coordinates.
    This can be computationally intensive for large point clouds.

    Code from:
    https://www.agisoft.com/forum/index.php?topic=11548.msg51834#msg51834
    """

    # Print to console to warn user that this can take a long time
    print('Computing RMSE. This can take a while... \n\n')
    # identify points from point cloud in active chunk
    point_cloud = chunk.tie_points
    points = point_cloud.points
    # get total number of point records
    npoints = len(points)
    # get point projections
    projections = chunk.tie_points.projections
    err_sum = 0
    num = 0
    point_ids = [-1] * len(point_cloud.tracks)
    point_errors = dict()
    for point_id in range(0, npoints):
        point_ids[points[point_id].track_id] = point_id
    # iterate through all cameras in the chunk and check that they have a valid
    # transform and coordinates
    for camera in chunk.cameras:
        if not camera.transform:
            continue
        for proj in projections[camera]:
            track_id = proj.track_id
            point_id = point_ids[track_id]
            if point_id < 0:
                continue
            point = points[point_id]
            # if the point is valid, then include it in error calculations
            if not point.valid:
                continue
            error = camera.error(point.coord, proj.coord).norm() ** 2
            err_sum += error
            num += 1
            if point_id not in point_errors.keys():
                point_errors[point_id] = [error]
            else:
                point_errors[point_id].append(error)
    # compute the combined RMSE of all points
    RMSE = math.sqrt(err_sum/num)
    return round(RMSE,6)

def getAntennaTransform(sensor):
    location = sensor.antenna.location
    if location is None:
        location = sensor.antenna.location_ref
    rotation = sensor.antenna.rotation
    if rotation is None:
        rotation = sensor.antenna.rotation_ref
    return Metashape.Matrix.Diag((1, -1, -1, 1)) * Metashape.Matrix.Translation(location) * Metashape.Matrix.Rotation(Metashape.Utils.ypr2mat(rotation))

def compute_camera_accuracy(chunk):
    """
    Code for computing the camera accuracy from:
    https://www.agisoft.com/forum/index.php?topic=11077.0
    """
    try:
        if float(".".join(str(Metashape.version).split('.',2)[:2])) >= 1.7:
            crs = chunk.crs
            sums = 0
            num = 0
            for cam in chunk.cameras:
                if not cam.transform:
                    continue
                transform = chunk.transform.matrix
                crs = chunk.crs
                if chunk.camera_crs:
                    transform = Metashape.CoordinateSystem.datumTransform(crs, chunk.camera_crs) * transform
                    crs = chunk.camera_crs
                ecef_crs = crs.geoccs
                if ecef_crs is None:
                    ecef_crs = Metashape.CoordinateSystem('LOCAL')
                camera_transform = transform * cam.transform
                antenna_transform = getAntennaTransform(cam.sensor)
                location_ecef = camera_transform.translation() + camera_transform.rotation() * antenna_transform.translation()
                rotation_ecef = camera_transform.rotation() * antenna_transform.rotation()
                est_loc = Metashape.CoordinateSystem.transform(location_ecef, ecef_crs, crs)
                ref_loc = cam.reference.location
                err_loc = Metashape.CoordinateSystem.transform(est_loc, crs, ecef_crs) - Metashape.CoordinateSystem.transform(ref_loc, crs, ecef_crs)
                err_loc = crs.localframe(location_ecef).rotation() * err_loc #gives x,y,z errors as vectors
                err_loc_norm = err_loc.norm()
                sums += err_loc_norm**2
                num += 1
        elif float(".".join(str(Metashape.version).split('.',2)[:2])) == 1.6:
            T = chunk.transform.matrix
            crs = chunk.crs
            sums = 0
            num = 0
            for camera in chunk.cameras:
                if not camera.transform:
                    continue
                if not camera.reference.location:
                    continue

                estimated_geoc = chunk.transform.matrix.mulp(camera.center)
                error = chunk.crs.unproject(camera.reference.location) - estimated_geoc
                error = error.norm()
                sums += error**2
                num += 1
        cam_acc = math.sqrt(sums / num)  
    except Exception as e:
        print('EXCEPTION encountered during execution of compute_camera_accuracy function:')
        print(e)
        print('ERROR calculating camera accuracy, setting to -9999.')
        cam_acc = -9999        
    return cam_acc

def activate_chunk(doc, chunk_name):
    """
    Activate chunk based on name
        args:
            doc = current Metashape.app.doc
            chunk_name = str name
        returns:
            chunk = activated chunk
    """
    # Get list of chunk labels
    chunk_label_list = [chunk.label for chunk in doc.chunks]
    # find all indices of chunks labeled chunk_name in document
    chunk_idx = [idx for idx, label in enumerate(chunk_label_list) if label == chunk_name]
    if len(chunk_idx) == 0:
        # no chunks with that label
        # print exception so it will be visible in console
        print('Exception: No chunk named ' + '"' + chunk_name + '"' + ' in project, stopping execution.')
        raise Exception('No chunk named ' + '"' + chunk_name + '"' + ' in project.')
    if len(chunk_idx) > 1:
        # more than one chunk with that label
        # print exception so it will be visible in console
        print('Exception: More than one chunk named ' + '"' + chunk_name + '"' + ' in project, stopping execution.')
        raise Exception('More than one chunk named ' + '"' + chunk_name + '"' + ' in project.')
    # if only one chunk with that name, then activate chunk
    doc.chunk = doc.chunks[chunk_idx[0]]
    chunk = doc.chunk
    return chunk


def align_images(chunk, keypointlimit, tiepointlimit, cam_opt_parameters, **kwargs):
    """
    Aligns images in chunk.  Alignment accuracy, keypointlimit, and preselection options can be set by keyword arguments.
    Performs camera optimization after alignment using parameters defined in cam_opt_parameters dictionary.
        args:
              chunk = chunk on which to perform function
              keypointlimit = key point limit for alignment
              cam_opt_parameters = dictionary of camera optimization parameters
        kwargs:
              generic_preselection = boolean [Default=True]
              reference_preselection = boolean [Default=True]
              reference_preselection_mode = 'ReferencePreselectionMode'
              accuracy = alignment accuracy. allowed keywords:
                        highest, high, medium, low, lowest
              compute_rmse = boolean
              mask_keypoints = boolean
              mask_tiepoints = boolean
              log = boolean
              proclog = str name of proclog
    """
    # As of 1.6.x, the API has updated from Metashape.accuracy.HighAccuracy to downscaling values
    # See forum for more info: https://www.agisoft.com/forum/index.php?topic=11697.0
    # The accuracy_switcher is an efficient approach to mapping the specified user input accuracy to the
    # equivalent API value.
    accuracy_switcher = {
        'highest': 0,
        'high': 1,
        'medium': 2,
        'low': 4,
        'lowest': 8
        }
    # The preselection switcher is an efficient approach to mapping user input values to
    # the appropriate Metashape API values.
    preselection_switcher = {
        'source': Metashape.ReferencePreselectionMode(0),
        'estimated': Metashape.ReferencePreselectionMode(1),
        'sequential': Metashape.ReferencePreselectionMode(2)
        }
    # ALIGNMENT SETTINGS
    num_keypoints = keypointlimit
    num_tiepoints = tiepointlimit
    # set kwarg defaults
    align_generic = True
    align_reference = True
    align_reference_mode = Metashape.ReferencePreselectionMode(0)  # source
    # Metashape API 1.6.x uses downscaling values.
    # default alignment accuracy set to HIGH, which corresponds to downscaling value of 1
    alignment_accuracy = 1
    # change if needed from kwargs
    if 'generic_preselection' in kwargs:
        align_generic = kwargs['generic_preselection']
    if 'reference_preselection' in kwargs:
        align_reference = kwargs['reference_preselection']
    if 'reference_preselection_mode' in kwargs:
        align_reference_mode = preselection_switcher[str(kwargs['reference_preselection_mode']).lower()]
    if 'accuracy' in kwargs:
        alignment_accuracy = accuracy_switcher[str(kwargs['accuracy']).lower()]
    if 'mask_keypoints' in kwargs:
        maskkeypoints = kwargs['mask_keypoints']
    if 'mask_tiepoints' in kwargs:
        masktiepoints = kwargs['mask_tiepoints']

    # get start time for processing log
    starttime = datetime.now()

    # align all frames in chunk
    if align_reference:
        chunk.matchPhotos(downscale=alignment_accuracy, generic_preselection=align_generic,
                          reference_preselection=align_reference, reference_preselection_mode=align_reference_mode, keypoint_limit=num_keypoints,
                          tiepoint_limit=num_tiepoints, filter_mask=maskkeypoints, mask_tiepoints=masktiepoints)
    else:
        chunk.matchPhotos(downscale=alignment_accuracy, generic_preselection=align_generic,
                          reference_preselection=align_reference, keypoint_limit=num_keypoints,
                          tiepoint_limit=num_tiepoints, filter_mask=maskkeypoints, mask_tiepoints=masktiepoints)
    chunk.alignCameras()
    # perform initial optimization MAKE SURE YOU SELECT VARIABLES YOU WANT
    chunk.optimizeCameras(fit_f=cam_opt_parameters['cal_f'],
                          fit_cx=cam_opt_parameters['cal_cx'],
                          fit_cy=cam_opt_parameters['cal_cy'],
                          fit_b1=cam_opt_parameters['cal_b1'],
                          fit_b2=cam_opt_parameters['cal_b2'],
                          fit_k1=cam_opt_parameters['cal_k1'],
                          fit_k2=cam_opt_parameters['cal_k2'],
                          fit_k3=cam_opt_parameters['cal_k3'],
                          fit_k4=cam_opt_parameters['cal_k4'],
                          fit_p1=cam_opt_parameters['cal_p1'],
                          fit_p2=cam_opt_parameters['cal_p2'],
                          fit_corrections=False)

    # get end time for processing log
    endtime = datetime.now()
    tdiff = endtime - starttime
    # count number of aligned images
    cameras = chunk.cameras
    naligned = len([True for camera in cameras if camera.transform])

    # rename the chunk based on the final Re threshold
    chunk.label = str(chunk.label).replace('Copy of ','',1) + '_Align'

    # print status
    print('Image alignment completed.\n' +
          str(naligned) + ' of ' + str(len(cameras)) + ' images aligned in chunk "' + chunk.label + '".\n')

    # Calculate camera accuracy and chunk rmse (if enabled)
    if 'compute_rmse' in kwargs:
        if kwargs['compute_rmse']:
            chunk_rmse = compute_RMSE(chunk)
        else:
            chunk_rmse = -9999
    else:
        chunk_rmse = compute_RMSE(chunk)
    cam_accuracy = compute_camera_accuracy(chunk)

    # Check if logging option enabled
    if 'log' in kwargs:
        #get accuracy keyword from downscale integer (reverse dictionary lookup)
        accuracy_keyword_from_downscale = list(accuracy_switcher.keys())[list(accuracy_switcher.values()).index(alignment_accuracy)]
        # check that filename defined
        if 'proclog' in kwargs:
            # write results to processing log
            with open(kwargs['proclog'], 'a') as f:
                f.write("\n")
                f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                f.write("Image Alignment: \n")
                f.write("Chunk: " + chunk.label + "\n")
                f.write("Keypointlimit: " + str(num_keypoints) + "\n")
                f.write("Tiepointlimit: " + str(num_tiepoints) + "\n")
                f.write("Alignment Accuracy: " + accuracy_keyword_from_downscale.capitalize() + "\n")
                f.write("Generic Preselection: " + str(align_generic) + "\n")
                f.write("Reference Preselection: " + str(align_reference) + "\n")
                f.write(str(naligned) + " of " + str(len(cameras)) + " images aligned.\n")
                f.write('Final camera lens calibration parameters: ' + ', '.join(
                    [k for k in cam_opt_parameters if cam_opt_parameters[k]]) + '\n')
                f.write('RMSE after alignment: ' + str(chunk_rmse) + '\n')
                f.write('Camera accuracy after alignment: ' + str(cam_accuracy) + '\n')
                f.write('Sigma0 after alignment: ' + str(chunk.meta['OptimizeCameras/sigma0']) + '\n')
                f.write("Start time: " + str(starttime) + "\n")
                f.write("End time: " + str(endtime) + "\n")
                f.write("Processing duration: " + str(tdiff) + "\n")
                f.write("\n")


def reconstruction_uncertainty(chunk, ru_filt_level_param, ru_cutoff, ru_increment, cam_opt_parameters, **kwargs):
    """
    Perform gradual selection on sparse cloud using Reconstruction Uncertainty ("Ru") filter.
    Filter and remove only a percentage (ru_cutoff) of overall points in each iteration.
    After deleting perform camera optimization using parameters defined in cam_opt_parameters dictionary.
    Iterate until desired level of reconstruction uncertainty is attained.
        args:
              chunk = chunk on which to perform function
              ru_filt_level_param = desired level of reconstruction uncertainty
              ru_cutoff = max percentage (0-1) of points to be deleted in one iteration
              ru_increment = value to increment grad selection filter in while loop
              cam_opt_parameters = dictionary of camera optimization parameters
        kwargs:
              ru_iterate_to_ru_level = boolean (False for workflow v2: function will run once and select
                                                      a Ru level that selects and deletes a percentage of
                                                      points = ru_cutoff, even if final Ru level is higher
                                                      than ru_filt_level_param.
                                                      Camera optimization will be performed once afterward.
                                                True for workflow v1: function will iterate. Each iteration will
                                                      select a Ru level that selects and deletes a percentage
                                                      of points no more than ru_cutoff. After point deletion,
                                                      camera optimization is performed. Iteration will continue
                                                      until a Ru level of ru_filt_level_param is acheived.
                                                )
              compute_rmse = boolean
              log = boolean
              proclog = str name of proclog
    """
    # initialize counter variables
    noptimized = 0
    ndeleted = 0
    ninc_reduced = 0

    #determine if looping until Ru=ru_filt_level_param (workflow v1) or running once (workflow v2)
    if 'ru_iterate_to_ru_level' in kwargs:
        if kwargs.get('ru_iterate_to_ru_level'):
            #if True set to a high number which will allow iterations to continue until
            #Ru filter selects 0 points.
            n_iterations = 10000 #a high number, far less iterations are likely needed
        else:
            #if -ru_iterate_to_ru_level in kwargs but set to False
            n_iterations = 1
    else:
        # if not in kwargs then default is to run once
        n_iterations = 1

    # get start time for processing log
    starttime = datetime.now()
    # get initial point count
    points = chunk.tie_points.points
    init_pointcount = len([True for point in points if point.valid is True])

    while True and noptimized < n_iterations:
        # define threshold variables
        points = chunk.tie_points.points
        f = Metashape.TiePoints.Filter()
        threshold_ru = ru_filt_level_param
        print("initializing with Ru =", threshold_ru)
        # initialize filter for Ru
        f.init(chunk, criterion=Metashape.TiePoints.Filter.ReconstructionUncertainty)
        f.selectPoints(threshold_ru)
        # calculate number of selected points
        nselected = len([True for point in points if point.valid is True and point.selected is True])
        print(nselected, " points selected")
        if nselected == 0:
            break
        npoints = len(points)
        while nselected * (1 / ru_cutoff) > npoints:
            print("Ru threshold ", threshold_ru, "selected ", nselected, "/", npoints, "(",
                  round(nselected / npoints * 100, 4), " %) of  points. Adjusting")
            threshold_ru = threshold_ru + ru_increment
            f.selectPoints(threshold_ru)
            nselected = len([True for point in points if point.valid is True and point.selected is True])
            # if increment is too large, 0 points will be selected. Adjust increment value downward by 25%. Only do this 10 times before stopping.
            if nselected == 0:
                ru_increment = ru_increment * 0.75
                ninc_reduced = ninc_reduced + 1
                if ninc_reduced > 10:
                    print('Ru filter increment reduction called ten times, stopping execution.')
                    raise ValueError('Ru filter increment reduction called ten times, stopping execution.')
                else:
                    print("Ru increment too large, reducing to " + str(ru_increment) + ".")

        print("Ru threshold ", threshold_ru, " is ", round(nselected / npoints * 100, 4),
              "% of total points. Ready to delete")
        ndeleted = ndeleted + nselected
        chunk.tie_points.removeSelectedPoints()
        print("Ru", threshold_ru, "deleted", nselected, "points")
        chunk.optimizeCameras(fit_f=cam_opt_parameters['cal_f'],
                              fit_cx=cam_opt_parameters['cal_cx'],
                              fit_cy=cam_opt_parameters['cal_cy'],
                              fit_b1=cam_opt_parameters['cal_b1'],
                              fit_b2=cam_opt_parameters['cal_b2'],
                              fit_k1=cam_opt_parameters['cal_k1'],
                              fit_k2=cam_opt_parameters['cal_k2'],
                              fit_k3=cam_opt_parameters['cal_k3'],
                              fit_k4=cam_opt_parameters['cal_k4'],
                              fit_p1=cam_opt_parameters['cal_p1'],
                              fit_p2=cam_opt_parameters['cal_p2'],
                              fit_corrections=False)

        noptimized = noptimized + 1
        print("Completed optimization # " + str(noptimized) + "\n\n")
    if noptimized==0:
        print("WARNING: No optimizations occurred!")
        # break

    # get end time for processing log
    endtime = datetime.now()
    tdiff = endtime - starttime
    # get end point count
    end_pointcount = len([True for point in points if point.valid is True])

    # rename the chunk based on the final Ru threshold
    chunk.label = str(chunk.label).replace('Copy of ','',1) + '_Ru' + str(round(threshold_ru,2))

    # Calculate camera accuracy and chunk rmse (if enabled)
    if 'compute_rmse' in kwargs:
        if kwargs['compute_rmse']:
            chunk_rmse = compute_RMSE(chunk)
        else:
            chunk_rmse = -9999
    else:
        chunk_rmse = compute_RMSE(chunk)
    cam_accuracy = compute_camera_accuracy(chunk)

    # print status
    print("RMSE after Ru: ",str(chunk_rmse))
    print('Camera accuracy after Ru: ' + str(cam_accuracy))
    print('Reconstruction Uncertainty optimization completed.\n' +
          str(ndeleted) + ' of ' + str(init_pointcount) + ' removed in ' + str(
        noptimized) + ' optimizations on chunk "' + chunk.label + '".\n')

    # Check if logging option enabled
    if 'log' in kwargs:
        # check that filename defined
        if 'proclog' in kwargs:
            # write results to processing log
            with open(kwargs['proclog'], 'a') as f:
                f.write("\n")
                f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                f.write("Reconstruction Uncertainty optimization:\n")
                f.write("Chunk: " + chunk.label + "\n")
                f.write(str(ndeleted) + " of " + str(init_pointcount) + " removed in " + str(
                    noptimized) + " optimizations.\n")
                f.write("Final point count: " + str(end_pointcount) + "\n")
                f.write("Final Reconstruction Uncertainty: " + str(round(threshold_ru,2)) + "\n")
                f.write('Final camera lens calibration parameters: ' + ', '.join(
                    [k for k in cam_opt_parameters if cam_opt_parameters[k]]) + '\n')
                f.write('RMSE after Ru: ' + str(chunk_rmse) + '\n')
                f.write('Camera accuracy after Ru: ' + str(cam_accuracy) + '\n')
                f.write('Sigma0 after Ru: ' + str(chunk.meta['OptimizeCameras/sigma0']) + '\n')
                f.write("Start time: " + str(starttime) + "\n")
                f.write("End time: " + str(endtime) + "\n")
                f.write("Processing duration: " + str(tdiff) + "\n")
                f.write("\n")


def projection_accuracy(chunk, pa_filt_level_param, pa_cutoff, pa_increment, cam_opt_parameters, **kwargs):
    """
    Perform gradual selection on sparse cloud using Projection Accuracy ("Pa") filter.
    Filter and remove only a percentage (pa_cutoff) of overall points in each iteration.
    After deleting perform camera optimization using parameters defined in cam_opt_parameters dictionary.
    Iterate until desired level of projection accuracy is attained.
        args:
              chunk = chunk on which to perform function
              pa_filt_level_param = desired level of projection accuracy
              pa_cutoff = max percentage (0-1) of points to be deleted in one iteration
              pa_increment = value to increment grad selection filter in while loop
              cam_opt_parameters = dictionary of camera optimization parameters
        kwargs:
              pa_iterate_to_pa_level = boolean (False for workflow v2: function will run once and select
                                          a Pa level that selects and deletes a percentage of
                                          points = pa_cutoff, even if final Pa level is higher
                                          than pa_filt_level_param.
                                          Camera optimization will be performed once afterward.
                                    True for workflow v1: function will iterate. Each iteration will
                                          select a Pa level that selects and deletes a percentage
                                          of points no more than pa_cutoff. After point deletion,
                                          camera optimization is performed. Iteration will continue
                                          until a Pa level of pa_filt_level_param is acheived.
                                    )
              compute_rmse = boolean
              log = boolean
              proclog = str name of proclog
    """
    # initialize counter variables
    noptimized = 0
    ndeleted = 0
    ninc_reduced = 0

    #determine if looping until Pa=pa_filt_level_param (workflow v1) or running once (workflow v2)
    if 'pa_iterate_to_pa_level' in kwargs:
        if kwargs.get('pa_iterate_to_pa_level'):
            #if True set to a high number which will allow iterations to continue until
            #Pa filter selects 0 points.
            n_iterations = 10000 #a high number, far less iterations are likely needed
        else:
            #if -pa_iterate_to_pa_level in kwargs but set to False
            n_iterations = 1
    else:
        # if not in kwargs then default is to run once
        n_iterations = 1

    # get start time for processing log
    starttime = datetime.now()
    # get initial point count
    points = chunk.tie_points.points
    init_pointcount = len([True for point in points if point.valid is True])

    while True and noptimized < n_iterations:
        # define threshold variables
        points = chunk.tie_points.points
        f = Metashape.TiePoints.Filter()
        threshold_pa = pa_filt_level_param
        print("initializing with Pa =", threshold_pa)
        # initialize filter for Pa
        f.init(chunk, criterion=Metashape.TiePoints.Filter.ProjectionAccuracy)
        f.selectPoints(threshold_pa)
        # calculate number of selected points
        nselected = len([True for point in points if point.valid is True and point.selected is True])
        print(nselected, " points selected")
        if nselected == 0:
            break
        npoints = len(points)

        while nselected * (1 / pa_cutoff) > npoints:
            print("Pa threshold ", threshold_pa, "selected ", nselected, "/", npoints, "(",
                  round(nselected / npoints * 100, 4), " %) of  points. Adjusting")
            threshold_pa = threshold_pa + pa_increment
            f.selectPoints(threshold_pa)
            nselected = len([True for point in points if point.valid is True and point.selected is True])
            # if increment is too large, 0 points will be selected. Adjust increment value downward by 25%. Only do this 10 times before stopping.
            if nselected == 0:
                pa_increment = pa_increment * 0.75
                ninc_reduced = ninc_reduced + 1
                if ninc_reduced > 10:
                    print('Pa filter increment reduction called ten times, stopping execution.')
                    raise ValueError('Pa filter increment reduction called ten times, stopping execution.')
                else:
                    print("Pa increment too large, reducing to " + str(pa_increment) + ".")

        print("Pa threshold ", threshold_pa, " is ", round(nselected / npoints * 100, 4),
              "% of total points. Ready to delete")
        ndeleted = ndeleted + nselected
        chunk.tie_points.removeSelectedPoints()
        print("Pa", threshold_pa, "deleted", nselected, "points")
        chunk.optimizeCameras(fit_f=cam_opt_parameters['cal_f'],
                              fit_cx=cam_opt_parameters['cal_cx'],
                              fit_cy=cam_opt_parameters['cal_cy'],
                              fit_b1=cam_opt_parameters['cal_b1'],
                              fit_b2=cam_opt_parameters['cal_b2'],
                              fit_k1=cam_opt_parameters['cal_k1'],
                              fit_k2=cam_opt_parameters['cal_k2'],
                              fit_k3=cam_opt_parameters['cal_k3'],
                              fit_k4=cam_opt_parameters['cal_k4'],
                              fit_p1=cam_opt_parameters['cal_p1'],
                              fit_p2=cam_opt_parameters['cal_p2'],
                              fit_corrections=False)

        noptimized = noptimized + 1
        print("Completed optimization # " + str(noptimized) + "\n\n")
    if noptimized==0:
        print("WARNING: No optimizations occurred!")

    # get end time for processing log
    endtime = datetime.now()
    tdiff = endtime - starttime
    # get end point count
    end_pointcount = len([True for point in points if point.valid is True])

    # rename the chunk based on the final Pa threshold
    chunk.label = str(chunk.label).replace('Copy of ','',1) + '_Pa' + str(round(threshold_pa,2))

    # Calculate camera accuracy and chunk rmse (if enabled)
    if 'compute_rmse' in kwargs:
        if kwargs['compute_rmse']:
            chunk_rmse = compute_RMSE(chunk)
        else:
            chunk_rmse = -9999
    else:
        chunk_rmse = compute_RMSE(chunk)
    cam_accuracy = compute_camera_accuracy(chunk)

    # print status
    print("RMSE after Pa: ",str(chunk_rmse))
    print('Camera accuracy after Pa: ' + str(cam_accuracy))
    print('Projection Accuracy optimization completed.\n' +
          str(ndeleted) + ' of ' + str(init_pointcount) + ' removed in ' + str(
        noptimized) + ' optimizations on chunk "' + chunk.label + '".\n')

    # Check if logging option enabled
    if 'log' in kwargs:
        # check that filename defined
        if 'proclog' in kwargs:
            # write results to processing log
            with open(kwargs['proclog'], 'a') as f:
                f.write("\n")
                f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                f.write("Projection Accuracy optimization:\n")
                f.write("Chunk: " + chunk.label + "\n")
                f.write(str(ndeleted) + " of " + str(init_pointcount) + " removed in " + str(
                    noptimized) + " optimizations.\n")
                f.write("Final point count: " + str(end_pointcount) + "\n")
                f.write("Final Projection Accuracy: " + str(round(threshold_pa,2)) + "\n")
                f.write('Final camera lens calibration parameters: ' + ', '.join(
                    [k for k in cam_opt_parameters if cam_opt_parameters[k]]) + '\n')
                f.write('RMSE after Pa: ' + str(chunk_rmse) + '\n')
                f.write('Camera accuracy after Pa: ' + str(cam_accuracy) + '\n')
                f.write('Sigma0 after Pa: ' + str(chunk.meta['OptimizeCameras/sigma0']) + '\n')
                f.write("Start time: " + str(starttime) + "\n")
                f.write("End time: " + str(endtime) + "\n")
                f.write("Processing duration: " + str(tdiff) + "\n")
                f.write("\n")


def reprojection_error(chunk, re_filt_level_param, re_cutoff, re_increment, cam_opt_parameters, fit_additional_corr, **kwargs):
    """
    Perform gradual selection on sparse cloud using Reprojection Error ("Re") filter.
    Filter and remove only a percentage (re_cutoff) of overall points in each iteration.
    After deleting perform camera optimization using parameters defined in cam_opt_parameters dictionary.
    Iterate until desired level of reprojection error is attained.
        args:
              chunk = chunk on which to perform function
              re_filt_level_param = desired level of reprojection error
              re_cutoff = max percentage (0-1) of points to be deleted in one iteration
              re_increment = value to increment grad selection filter in while loop
              cam_opt_parameters = dictionary of camera optimization parameters
              fit_additional_corr = fit additional parameters during camera optimization (boolean)
        kwargs:
              adapt_cam_opt = Enable additional camera opt. parameters if re_filt_level_param falls below threshold (boolean)
              adapt_cam_level = re_filt_level_param below which to enable additional camera opt. params (float)
              adapt_cam_param = dictionary of additional camera optimization parameters to enable
              final_tie_point_accuracy = set final tie point accuracy before final optimization
              early_stop = enable early_stop to prevent Re from excessive iterations in some instances (bool)
              early_stop_min_iterations = minimum number of iterations to perform before allowing early stop
              early_stop_variance = max difference between final RMSE and target RMSE before allowing early stop
              compute_rmse = boolean
              log = boolean
              proclog = str name of proclog
    """
    # initialize counter variables
    noptimized = 0
    ndeleted = 0
    ninc_reduced = 0
    s0_end_gradual_selection = 0

    #initialize list for tabulated iteration details
    re_list = []  #for single iteration
    re_tabulated_list = []  #to tabulate iterations

    # get start time for processing log
    starttime = datetime.now()
    # get initial point count
    points = chunk.tie_points.points
    init_pointcount = len([True for point in points if point.valid is True])

    threshold_re = re_filt_level_param

    # Set iteration criteria for loop. If compute_rmse enabled [default], use chunk_rmse, otherwise
    # use re_filt_level_param + 1 so that looping continues until Re filter selects 0 points.
    if 'compute_rmse' in kwargs:
        if kwargs['compute_rmse']:
            #if True
            chunk_rmse = compute_RMSE(chunk)
            iter_criteria = chunk_rmse
        else:
            # if in kwargs but compute_rmse=False, set chunk_rmse to -9999 and set initial iteration criteria to a
            # value above re_filt_level_param, which will cause 'iter_criteria > re_filt_level_param'
            # to always evaluate to True. This will continue the loop until Re filter selects 0 points.
            chunk_rmse = -9999
            iter_criteria = re_filt_level_param + 1
    else:
        #if not in kwargs then default iteration criteria is chunk_rmse
        chunk_rmse = compute_RMSE(chunk)
        iter_criteria = chunk_rmse

    print("Initial RMSE: ",str(chunk_rmse)," (Target RMSE: ",str(re_filt_level_param),")")


    while True and iter_criteria > re_filt_level_param:
        # define threshold variables
        points = chunk.tie_points.points
        f = Metashape.TiePoints.Filter()
        threshold_re = re_filt_level_param
        print("initializing with Re =", threshold_re)
        # initialize filter for Re
        f.init(chunk, criterion=Metashape.TiePoints.Filter.ReprojectionError)
        f.selectPoints(threshold_re)
        # calculate number of selected points
        nselected = len([True for point in points if point.valid is True and point.selected is True])
        print(nselected, " points selected")
        if nselected == 0:
            break
        npoints = len(points)

        # calculate the Sigma0 (used for logging)
        s0_init = chunk.meta['OptimizeCameras/sigma0']

        while nselected * (1 / re_cutoff) > npoints:
            print("Sigma0: ", s0_init)
            print("Re threshold ", threshold_re, "selected ", nselected, "/", npoints, "(",
                  round(nselected / npoints * 100, 4), " %) of  points. Adjusting")
            threshold_re = threshold_re + re_increment
            f.selectPoints(threshold_re)
            nselected = len([True for point in points if point.valid is True and point.selected is True])

            # if increment is too large, 0 points will be selected. Adjust increment value downward by 25%.
            # Only do this 10 times before stopping.
            if nselected == 0:
                re_increment = re_increment * 0.75
                ninc_reduced = ninc_reduced + 1
                if ninc_reduced > 10:
                    print('Re filter increment reduction called ten times, stopping execution.')
                    raise ValueError('Re filter increment reduction called ten times, stopping execution.')
                else:
                    print("Re increment too large, reducing to " + str(re_increment) + ".")

        #get current point count before deletion
        current_pointcount = len([True for point in points if point.valid is True])

        # write Re details to list for logging
        re_list.append(str(current_pointcount))
        re_list.append(str(nselected))
        re_list.append(str(s0_init))

        print("Re threshold ", threshold_re, " is ", round(nselected / npoints * 100, 4),
              "% of total points. Ready to delete")
        ndeleted = ndeleted + nselected
        chunk.tie_points.removeSelectedPoints()
        print("Re", threshold_re, "deleted", nselected, "points")

        # check if adaptive camera optimization parameters called
        if 'adapt_cam_opt' in kwargs:
            # if true
            if kwargs['adapt_cam_opt']:
                # check if other required kwargs present
                if 'adapt_cam_level' not in kwargs or 'adapt_cam_param' not in kwargs:
                # print exception so it will be visible in console, then raise exception
                    print('ArgumentError: '"'adapt_cam_opt'"' keyword called, but '"'adapt_cam_level'"' and '"'adapt_cam_param'"' not present.')
                    raise Exception(
                            'ArgumentError: '"'adapt_cam_opt'"' keyword called, but '"'adapt_cam_level'"' and '"'adapt_cam_param'"' not present.')
                # get 'adapt_cam_level', should be float
                adapt_cam_level = kwargs['adapt_cam_level']
                if not str(adapt_cam_level).replace('.','',1).isdigit():
                    # print exception so it will be visible in console, then raise exception
                    print('ArgumentError: '"'adapt_cam_level'"' keyword is not a number.')
                    raise Exception('ArgumentError: '"'adapt_cam_level'"' keyword is not a number.')

                # If threshold gets below adapt_cam_level, add additional camera params.
                if threshold_re < adapt_cam_level:
                    # then enable additional lens params
                    cam_opt_parameters = kwargs['adapt_cam_param']
                    cam_opt_parameters_str = str([k for (k, v) in cam_opt_parameters.items() if v])
                    cam_opt_parameters_str = cam_opt_parameters_str.replace('cal_','')
                    print('Re below ' +  str(adapt_cam_level) + ' pixel, enabling ' + cam_opt_parameters_str)

        chunk.optimizeCameras(fit_f=cam_opt_parameters['cal_f'],
                              fit_cx=cam_opt_parameters['cal_cx'],
                              fit_cy=cam_opt_parameters['cal_cy'],
                              fit_b1=cam_opt_parameters['cal_b1'],
                              fit_b2=cam_opt_parameters['cal_b2'],
                              fit_k1=cam_opt_parameters['cal_k1'],
                              fit_k2=cam_opt_parameters['cal_k2'],
                              fit_k3=cam_opt_parameters['cal_k3'],
                              fit_k4=cam_opt_parameters['cal_k4'],
                              fit_p1=cam_opt_parameters['cal_p1'],
                              fit_p2=cam_opt_parameters['cal_p2'],
                              fit_corrections=False)

        noptimized = noptimized + 1
        s0_end = chunk.meta['OptimizeCameras/sigma0']

        print("Completed optimization # " + str(noptimized) + "\n\n")
        print("Change in Sigma0: ", (float(s0_end) - float(s0_init)))
        print("Old Sigma0: ", s0_init, " --> Updated Sigma0: ", s0_end)

        # write Re details to list for logging
        re_list.append(str(s0_end))
        re_list.append(str(chunk_rmse)) #starting RMSE

        # Recompute RMSE if enabled
        if 'compute_rmse' in kwargs:
            if kwargs['compute_rmse']:
                #if True
                rmse_init_time = datetime.now()
                chunk_rmse = compute_RMSE(chunk)
                comp_rmse_time = datetime.now() - rmse_init_time
            else:
                # if in kwargs but False, set chunk_rmse to -9999
                chunk_rmse = -9999
                comp_rmse_time = -9999
        else:
            #if not in kwargs then default is to compute chunk_rmse
            rmse_init_time = datetime.now()
            chunk_rmse = compute_RMSE(chunk)
            comp_rmse_time = datetime.now() - rmse_init_time

        cam_accuracy = compute_camera_accuracy(chunk)
        print("RMSE: ",str(chunk_rmse)," (Target RMSE: ",str(re_filt_level_param),")")

        # write additional Re details to list for logging
        re_list.append(str(chunk_rmse)) #new temporary RMSE for this iteration
        re_list.append(str(cam_accuracy))
        re_list.append(str(comp_rmse_time))
        re_list.append("False")         #Fit additional corrections is False for these iterations

        # write Re details to list
        re_tabulated_list.append(re_list)
        # clear list for next iteration
        re_list = []

        # update the Sigma0, RMSE values
        s0_init = s0_end
        s0_end_gradual_selection = s0_end                 #Post gradual selection Sigma0 if last iteration
        chunk_rmse_after_gradual_selection = chunk_rmse   #Post gradual selection RMSE if last iteration

        # check for early stop
        if 'early_stop' in kwargs:
            # if true
            if kwargs['early_stop']:
                # check if other required kwargs present
                if 'early_stop_min_iterations' not in kwargs or 'early_stop_variance' not in kwargs:
                # if not, print exception so it will be visible in console, then raise exception
                    print('ArgumentError: '"'early_stop'"' keyword called, but '"'early_stop_min_iterations'"' and '"'early_stop_variance'"' not present.')
                    raise Exception(
                            'ArgumentError: '"'early_stop'"' keyword called, but '"'early_stop_min_iterations'"' and '"'early_stop_variance'"' not present.')
                # if args present, then check to see if early stop conditions met and break loop if so
                if noptimized >= kwargs['early_stop_min_iterations'] and threshold_re <= re_filt_level_param + kwargs['early_stop_variance']:
                    print("Early stop ACTIVATED.")
                    print("RMSE within " + str(kwargs['early_stop_variance'])
                          + " of target Re filter level (" + str(re_filt_level_param) + ") after " +
                          str(kwargs['early_stop_min_iterations']) +
                          " iterations.")
                    break

        #set iteration criteria for next iteration
        if 'compute_rmse' in kwargs:
            if kwargs['compute_rmse']:
                # if True set iteration to chunk_rmse
                iter_criteria = chunk_rmse
            else:
                # if in kwargs, but compute_rmse=False, set chunk_rmse to -9999 and keep iteration criteria at a
                # value above re_filt_level_param, which will cause 'iter_criteria > re_filt_level_param'
                # to always evaluate to True. This will continue the loop until Re filter selects 0 points.
                iter_criteria = re_filt_level_param + 1
                chunk_rmse = -9999
        else:
            #if not in kwargs then default iteration criteria is chunk_rmse
            iter_criteria = chunk_rmse

    if noptimized==0:
        print("WARNING: No optimizations occurred!")

    # the following lines follow the workflow of the published OFR (see beginning of code)
    if fit_additional_corr is True:
        # check that the updated tie point accuracy is in the keyword arguments
        if 'final_tie_point_accuracy' in kwargs:
            # change tie point accuracy before final optimization
            print("Changing tie point accuracy to " + str(kwargs['final_tie_point_accuracy']) + " for FINAL optimization")
            chunk.tiepoint_accuracy = kwargs['final_tie_point_accuracy']

        chunk_rmse_after_gradual_selection = compute_RMSE(chunk)

        chunk.optimizeCameras(fit_f=cam_opt_parameters['cal_f'],
                              fit_cx=cam_opt_parameters['cal_cx'],
                              fit_cy=cam_opt_parameters['cal_cy'],
                              fit_b1=cam_opt_parameters['cal_b1'],
                              fit_b2=cam_opt_parameters['cal_b2'],
                              fit_k1=cam_opt_parameters['cal_k1'],
                              fit_k2=cam_opt_parameters['cal_k2'],
                              fit_k3=cam_opt_parameters['cal_k3'],
                              fit_k4=cam_opt_parameters['cal_k4'],
                              fit_p1=cam_opt_parameters['cal_p1'],
                              fit_p2=cam_opt_parameters['cal_p2'],
                              fit_corrections=fit_additional_corr)

        noptimized = noptimized + 1
        s0_end = chunk.meta['OptimizeCameras/sigma0']

        print("Completed optimization with fit additional parameters ENABLED")
        print("Change in Sigma0: {}".format(float(s0_end)-float(s0_end_gradual_selection)))
        print("Old Sigma0: {0} --> Updated Sigma0: {1}".format(s0_end_gradual_selection, s0_end))

        # Recompute RMSE if enabled
        if 'compute_rmse' in kwargs:
            if kwargs['compute_rmse']:
                #if True, compute RMSE
                rmse_init_time = datetime.now()
                chunk_rmse = compute_RMSE(chunk)
                comp_rmse_time = datetime.now() - rmse_init_time
            else:
                # if in kwargs but False, set chunk_rmse to -9999
                chunk_rmse = -9999
                comp_rmse_time = -9999
        else:
            rmse_init_time = datetime.now()
            chunk_rmse = compute_RMSE(chunk)
            comp_rmse_time = datetime.now() - rmse_init_time

        cam_accuracy = compute_camera_accuracy(chunk)
        print("RMSE: ",str(chunk_rmse)," (Target RMSE: ",str(re_filt_level_param),")")

        #get current point count
        current_pointcount = len([True for point in points if point.valid is True])

        # write Re details to list for logging
        re_list.append(str(current_pointcount))
        re_list.append(str(0))           # number of points selected for removal
        re_list.append(str(s0_end_gradual_selection))  # Sigma0 at the end of Re gradual selections
        re_list.append(str(s0_end))      # updated (final) Sigma0
        re_list.append(str(chunk_rmse))  # new RMSE
        re_list.append(str(compute_camera_accuracy(chunk)))
        re_list.append(str(comp_rmse_time))
        re_list.append(str(fit_additional_corr))

        # write Re details to list
        re_tabulated_list.append(re_list)

    # get end time for processing log
    endtime = datetime.now()
    tdiff = endtime - starttime
    # get end point count
    end_pointcount = len([True for point in points if point.valid is True])

    # rename the chunk based on the final Re threshold
    chunk.label = str(chunk.label).replace('Copy of ','',1) + '_Re' + str(round(threshold_re,2))

    # print status
    print('RMSE after Re: {}'.format(str(chunk_rmse)))
    print('Camera accuracy after Re: {}'.format(str(cam_accuracy)))
    print('Reprojection Error optimization completed.\n' +
          str(ndeleted) + ' of ' + str(init_pointcount) + ' removed in ' + str(noptimized) +
          ' optimizations on chunk "' + chunk.label + '".\n')

    # Check if logging option enabled
    if 'log' in kwargs:
        # check that filename defined
        if 'proclog' in kwargs:
            # write results to processing log
            with open(kwargs['proclog'], 'a') as f:
                f.write("\n")
                f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                f.write("Reprojection Error optimization:\n")
                f.write("Chunk: " + chunk.label + "\n")
                f.write(str(ndeleted) + " of " + str(init_pointcount) + " removed in " + str(
                    noptimized) + " optimizations.\n")
                f.write("Final point count: " + str(end_pointcount) + "\n")
                f.write("Final Reprojection Error: " + str(round(threshold_re,2)) + "\n")
                f.write('Final camera lens calibration parameters: ' + ', '.join(
                    [k for k in cam_opt_parameters if cam_opt_parameters[k]]) + '\n')
                f.write('RMSE after Re: ' + str(chunk_rmse) + '\n')
                f.write('Camera accuracy after Re: ' + str(cam_accuracy) + '\n')
                f.write('Sigma0 after Re: ' + str(s0_end) + '\n')
                f.write("Start time: " + str(starttime) + "\n")
                f.write("End time: " + str(endtime) + "\n")
                f.write("Processing duration: " + str(tdiff) + "\n")
                f.write("\n")
                f.write("Reprojection Error reduction details:\n")
                # write tabular header
                f.write("Points_Before_Iteration,Points_Deleted,s0_Before,s0_After,RMSE_Before,RMSE_After,Camera_Accuracy_After,RMSE_Computation_Time,Fit_Additional_Corr\n")
                # write all rows in list to log file
                f.write("\n".join(str(item) for item in re_tabulated_list))
                f.write("\n")


def parse_command_line_args(parg, doc):
    """
    Parse command line arguments with argparse.
        args:
            parg: default Arg object with all defined defaults
        returns:
            parg: parsed Arg object with all args formatted.
    """

    # ============== HELPER FUNCTIONS =========================================
    # function to convert str args to boolean args
    def str_to_bool(s):
        """
        Converts str ['t','true','f','false'] to boolean, not case sensitive.
        Checks first if already a boolean.
        Raises exception if unexpected entry.
            args:
                s: str
            returns:
                out_boolean: output boolean [True or False]
        """
        #check to see if already boolean
        if isinstance(s, bool):
            out_boolean = s
        else:
            # remove quotes, commas, and case from s
            sf = s.lower().replace('"', '').replace("'", '').replace(',', '')
            # True
            if sf in ['t', 'true']:
                out_boolean = True
            # False
            elif sf in ['f', 'false']:
                out_boolean = False
            # Unexpected arg
            else:
                # print exception so it will be visible in console, then raise exception
                print('ArgumentError: Argument invalid. Expected boolean '
                      + 'got ' + '"' + str(s) + '"' + ' instead')
                raise Exception('ArgumentError: Argument invalid. Expected boolean '
                                + 'got ' + '"' + str(s) + '"' + ' instead')
        return out_boolean

    # function to convert camera param args to formatted list
    def cam_arg_to_param_list(cam_arg):
        """
        Converts camera parameter argument to formatted list, checks that all args
        are in expected list not case sensitive.  Doesn't work with quotes.
        Raises exception if unexpected entry.
            args:
                cam_arg: cam_param argument
            returns:
                out_cam_list: formatted camera param list
        """
        # Create set of all allowed camera optimization parameters
        cam_allowed = {'f', 'cx', 'cy', 'k1', 'k2', 'k3', 'p1', 'p2', 'k4', 'b1', 'b2'}
        # remove trialing commas, quotes, brackets and lowercase all
        camlist = [x.lower().replace(',', '').replace('"', '').replace('"', '').replace('[', '').replace(']', '') for x
                   in cam_arg]
        # check that all values passed are allowed
        if not set(camlist).issubset(cam_allowed):
            # print exception so it will be visible in console, then raise exception
            print('ArgumentError: Camera parameter list argument invalid.\n'
                  + 'Expected args: [f, cx, cy, k1, k2, k3, k4, b1, b2, p1, p2]\n'
                  + 'Unexpected arg found instead: ['
                  + str(set(camlist).difference(cam_allowed)).replace("'", '').replace('{', '').replace('}', '')
                  + ']\nCheck that list is called without quotes (example: -al_cam_param f, k1, k2)')
            raise Exception('ArgumentError: Camera parameter list argument invalid.\n'
                            + 'Expected args: [f, cx, cy, k1, k2, k3, k4, b1, b2, p1, p2]\n'
                            + 'Unexpected arg found instead: ['
                            + str(set(camlist).difference(cam_allowed)).replace("'", '').replace('{', '').replace('}',
                                                                                                                  '')
                            + ']\nCheck that list is called without quotes (example: -al_cam_param f, k1, k2)')
        # if all arguments allowed, set out_cam_list
        out_cam_list = camlist
        return out_cam_list


    # ===========================  BEGIN PARSER ==============================
    descriptionstr = ('  Script to run Metashape image alignment, and conduct gradual selection of sparse tiepoints. '
                      'Script begins on chunk designated by optional "'"-chunk"'" argument. If no chunk is designated, '
                      'the currently active chunk is used. Each operation creates a new chunk. The initial chunk is '
                      'copied to a new chunk and given a suffix of "'"_Align"'", "'"_Ru"'", "'"_Pa"'", or "'"_Re"'".')

    parser = argparse.ArgumentParser(description=descriptionstr, epilog='example: run Align_RuPaRe_v2.py -chunk myChunk '
                                                                        '-align '
                                                                        '-al_accuracy=high'
                                                                        '-al_kplim=60000 '
                                                                        '-al_generic=True '
                                                                        '-al_reference=True '
                                                                        '-al_reference_mode=source'
                                                                        '-ru -ru_level=11 '
                                                                        '-ru_cam_param f, cx, cy, k1, k2, k3 '
                                                                        '-pa -pa_level=2 '
                                                                        '-re -re_level=0.18 '
                                                                        '-re_final_tie_point_accuracy=0.3 '
                                                                        '-re_adapt_cam=True '
                                                                        '-re_fit_additional_corr=True '
                                                                        '-log my_output_logfile.txt')
    # =================== Chunk args ==========================================
    parser.add_argument('-chunk', '--initial_chunk', dest='initial_chunk', nargs='?', const=parg.initial_chunk,
                        type=str,
                        help='Initial chunk on which to perform process [default = currently active chunk]')
    # =================== Alignment args ======================================
    parser.add_argument('-align', '--align_images', dest='align', default=False, action='store_true',
                        help='Align images [default=DISABLED].')

    parser.add_argument('-al_accuracy', '--alignment_accuracy', dest='accuracy', nargs='?', const=parg.align_accuracy,
                        type=str,
                        help='Alignment accuracy (highest, high, medium, low, lowest) [default=high]')

    parser.add_argument('-al_kplim', '--align_keypointlimit', dest='kplim', nargs='?', const=parg.keypointlimit,
                        type=int,
                        help='Alignment keypointlimit, set to 0 for unlimited [default=60,000]')

    parser.add_argument('-al_tplim', '--align_tiepointlimit', dest='tplim', nargs='?', const=parg.tiepointlimit,
                        type=int,
                        help='Alignment tiepointlimit, set to 0 for unlimited [default=0]')

    # action="store_true" doesn't work for these because need to be able to set false, need to convert str to boolean
    parser.add_argument('-al_generic', '--align_generic_preselection', dest='gen_preselect', nargs='?',
                        const=parg.gen_preselect, type=str,
                        help='Alignment generic preselection [default=True]')
    # action="store_true" doesn't work for these because need to be able to set false, need to convert str to boolean
    parser.add_argument('-al_reference', '--align_reference_preselection', dest='ref_preselect', nargs='?',
                        const=parg.ref_preselect, type=str,
                        help='Alignment reference preselection [default=True]')

    parser.add_argument('-al_reference_mode', '--align_reference_preselection_mode', dest='ref_preselect_option', nargs='?',
                        const=parg.ref_preselect_option, type=str,
                        help='Alignment reference preselection mode [default=Source]')

    parser.add_argument('-al_cam_param', '--align_camera_opt_param', dest='al_cam', nargs='*',
                        help='Camera optimization parameters used for optimization after aligment'
                             + '[default="'"f"'", "'"cx"'", "'"cy"'", "'"k1"'", "'"k2"'", "'"k3"'", "'"p1"'", "'"p2"'"]')

    parser.add_argument('-al_maskkeypoints', '--align_maskkeypoints', dest='al_maskkeypoints', nargs='?',
                        const=parg.al_maskkeypoints, type=str,
                        help='Mask key points during alignment. [default=False]')

    parser.add_argument('-al_masktiepoints', '--align_masktiepoints', dest='al_masktiepoints', nargs='?',
                        const=parg.al_masktiepoints, type=str,
                        help='Filter tie points by masks during alignment. [default=False]')

    # =================== Ru args =============================================
    parser.add_argument('-ru', '--reconstruction_uncertainty', dest='ru', default=False, action='store_true',
                        help='Reconstruction Uncertainty [default=DISABLED]')

    parser.add_argument('-ru_level', '--reconstruction_uncertainty_level', dest='ru_level', nargs='?',
                        const=parg.ru_filt_level, type=float,
                        help='Reconstruction Uncertainty filter level, optimum value 10-15 [default=10]')

    parser.add_argument('-ru_cam_param', '--reconstruction_uncertainty_camera_opt_param', dest='ru_cam', nargs='*',
                        help='Camera optimization parameters used for optimization during Ru iterations'
                             + '[default="'"f"'", "'"cx"'", "'"cy"'", "'"k1"'", "'"k2"'", "'"k3"'", "'"p1"'", "'"p2"'"]')

    parser.add_argument('-ru_max_percentage_delete', '--reconstruction_uncertainty_max_percentage_delete', dest='ru_cutoff', nargs='?',
                        const=parg.ru_cutoff, type=float,
                        help='Maximum percentage (0-1) of sparse points selected and deleted by Ru filter [default=0.50]')

    parser.add_argument('-ru_increment', '--reconstruction_uncertainty_increment', dest='ru_increment', nargs='?',
                        const=parg.ru_increment, type=float,
                        help='Value to use to increment Ru filter level [default=0.1]')

    # action="store_true" doesn't work for these because need to be able to set false, need to convert str to boolean
    parser.add_argument('-ru_iterate_to_ru_level', '--reconstruction_uncertainty_iterate_to_ru_level', dest='ru_iterate_to_ru_level', nargs='?',
                       const=parg.ru_iterate_to_ru_level, type=str,
                       help='Iterate Reconstruction Uncertainty filter until Ru level acheived, boolean [default=False]')

    # =================== Pa args =============================================
    parser.add_argument('-pa', '--projection_accuracy', dest='pa', default=False, action='store_true',
                        help='Projection Accuracy [default=DISABLED]')

    parser.add_argument('-pa_level', '--projection_accuracy_level', dest='pa_level', nargs='?',
                        const=parg.pa_filt_level, type=float,
                        help='Projection Accuracy filter level, optimum value 2-4 [default=3]')

    parser.add_argument('-pa_cam_param', '--projection_accuracy_camera_opt_param', dest='pa_cam', nargs='*',
                        help='Camera optimization parameters used for optimization during Pa iterations'
                             + '[default="'"f"'", "'"cx"'", "'"cy"'", "'"k1"'", "'"k2"'", "'"k3"'", "'"p1"'", "'"p2"'"]')

    parser.add_argument('-pa_max_percentage_delete', '--projection_accuracy_max_percentage_delete', dest='pa_cutoff', nargs='?',
                        const=parg.pa_cutoff, type=float,
                        help='Maximum percentage (0-1) of sparse points selected and deleted by Pa filter [default=0.50]')

    parser.add_argument('-pa_increment', '--projection_accuracy_increment', dest='pa_increment', nargs='?',
                        const=parg.pa_increment, type=float,
                        help='Value to use to increment Pa filter level [default=0.1]')

    # action="store_true" doesn't work for these because need to be able to set false, need to convert str to boolean
    parser.add_argument('-pa_iterate_to_pa_level', '--projection_accuracy_iterate_to_pa_level', dest='pa_iterate_to_pa_level', nargs='?',
                       const=parg.pa_iterate_to_pa_level, type=str,
                       help='Iterate Projection Accuracy filter until Pa level acheived, boolean [default=False]')

    # =================== Re args =============================================
    parser.add_argument('-re', '--reprojection_error', dest='re', default=False, action='store_true',
                        help='Reprojection Error, optimum value 0.3 [default=0.3]')

    parser.add_argument('-re_level', '--reprojection_error_level', dest='re_level', nargs='?',
                        const=parg.re_filt_level, type=float,
                        help='Projection Accuracy filter level, optimum value 2-4 [default=3]')

    parser.add_argument('-re_cam_param', '--reprojection_error_camera_opt_param', dest='re_cam', nargs='*',
                        help='Camera optimization parameters used for optimization during Re iterations'
                             + '[default="'"f"'", "'"cx"'", "'"cy"'", "'"k1"'", "'"k2"'", "'"k3"'", "'"p1"'", "'"p2"'"]')

    parser.add_argument('-re_adapt_cam', '--reprojection_error_adaptive_cam', dest='re_adapt', nargs='?',
                        const=parg.re_adapt, type=str,
                        help='Enable adaptive camera optimization parameters at Re pixel threshold [default=True]')

    parser.add_argument('-re_adapt_level', '--reprojection_error_adaptive_cam_level', dest='re_adapt_level', nargs='?',
                        const=parg.re_adapt_level, type=float,
                        help='Re pixel threshold below which to enable adapted camera parameters [default=1]')

    parser.add_argument('-re_final_tie_point_accuracy', '--reprojection_error_final_tie_point_accuracy', dest='re_final_tie_point_accuracy', nargs='?',
                        const=parg.re_final_tie_point_accuracy, type=float,
                        help='Updated tie point accuracy after final round of Re iterations [default=0.3]')

    parser.add_argument('-re_adapt_cam_param', '--reprojection_error_adapt_camera_param', dest='re_adapt_add_cam_param', nargs='*',
                        help='Additional camera optimization parameters used when below Re pixel threshold'
                             + '[default="'"k4"'", "'"b1"'", "'"b2"'", "'"p1"'", "'"p2"'"]')

    parser.add_argument('-re_fit_additional_corr', '--reprojection_error_fit_additional_corr', dest='re_fit_additional_corr', nargs='?',
                        const=parg.re_fit_additional_corr, type=str,
                        help='ENABLE "fit additional corrections" and re-optimize cameras at the end of the final Re iteration'
                             + '[default=True]')

    parser.add_argument('-re_max_percentage_delete', '--reprojection_error_max_percentage_delete', dest='re_cutoff', nargs='?',
                        const=parg.re_cutoff, type=float,
                        help='Maximum percentage (0-1) of sparse points selected and deleted by Re filter [default=0.10]')

    parser.add_argument('-re_increment', '--reprojection_error_increment', dest='re_increment', nargs='?',
                        const=parg.re_increment, type=float,
                        help='Value to use to increment Re filter level [default=0.01]')

    parser.add_argument('-re_early_stop', '--reprojection_error_early_stop', dest='re_early_stop', nargs='?',
                        const=parg.re_early_stop, type=str,
                        help='Stop Re early to prevent excessive iterations. If no additional arguments called, a default minimum number'
                             + ' of iterations (-re_early_stop_min_iterations) will be performed , then iterations will be stopped once '
                             + 'Re level is within a set range (-re_early_stop_variance) of target -re_level. [default=False]')

    parser.add_argument('-re_early_stop_min_iterations', '--reprojection_error_early_stop_min_iterations', dest='re_early_stop_min_iterations', nargs='?',
                        const=parg.re_early_stop_min_iterations, type=int,
                        help='Minimum number of Re iterations to perform before allowing early stop [default=5]')

    parser.add_argument('-re_early_stop_variance', '--reprojection_error_early_stop_variance', dest='re_early_stop_variance', nargs='?',
                        const=parg.re_early_stop_variance, type=float,
                        help='Allowed variance from target rmse for Re early stop [default=0.005]')

    # =================== Logging args =============================================
    parser.add_argument('-log', '--logfile', dest='logfile', nargs='?', const='default.txt', type=str,
                        help='Create or append to log file. [default name = XXXXX_ProcessingLog.txt]')

    # =================== Compute RMSE arg =============================================
    parser.add_argument('-compute_rmse', '--compute_rmse', dest='compute_rmse', nargs='?',
                        const=parg.compute_rmse, type=str,
                        help='Compute RMSE of points during iterations. [default=True]')

    # Parse known and unknown args
    try:
        arglist, unknown_args = parser.parse_known_args()
    except:
        # this will catch invalid argument types and prevent the default argparse behavior of showing usage
        # (which crashes Metashape) when script invoked from 'Run Script' dialog box.
        # print exception so it will be visible in console, then raise exception
        print('ArgumentError: Possible argument type error. Stopping execution.')
        raise Exception(
            'ArgumentError: Possible argument type error. Stopping execution.')

    # check if any unknown args, if so, warn user and stop execution.  This will prevent the default argparse
    # behavior of showing usage (which crashes Metashape) when script invoked from 'Run Script' dialog box.
    if unknown_args:
        # print exception so it will be visible in console, then raise exception
        print('ArgumentError: unrecognized arguments found: ' + str(unknown_args) + '. Stopping execution.')
        raise Exception(
            'ArgumentError: unrecognized arguments found: ' + str(unknown_args) + '. Stopping execution.')


    # =================== CONFIGURE ARGS ========================================
    # Chunk argument
    if arglist.initial_chunk is not None:
        #remove quotes, and trailing commas
        chstr = arglist.initial_chunk.replace("'",'').replace('"','').replace(',','')
        parg.initial_chunk = chstr

    # -----------------Align arguments-----------------------
    if arglist.align:
        parg.align = True
    # Check if any -align options called without -align argument
    alargs = [arglist.accuracy, arglist.gen_preselect, arglist.ref_preselect, arglist.kplim, arglist.tplim, arglist.al_cam, arglist.al_maskkeypoints, arglist.al_masktiepoints]
    if any(alargs) and not arglist.align:
        # an -al argument was called without -align also being called, raise exception
        # print exception so it will be visible in console, then raise exception
        print('ArgumentError: an -alignment (-al) option was called without the --align_images(-al) also being called.')
        raise Exception(
            'ArgumentError: an -alignment (-al) option was called without the --align_images(-al) also being called.')

    # alignment accuracy
    if arglist.accuracy is not None:
        # remove possible quotes
        accopt = arglist.accuracy.replace('"', '').replace("'", '')
    else:
        # use default
        accopt = parg.align_accuracy

    # check that accuracy keyword is valid
    if not accopt.lower() in ['highest', 'high', 'medium', 'low', 'lowest']:
        # print exception so it will be visible in console, then raise exception
        print('ArgumentError: --alignment_accuracy argument invalid. Expected'
              + '[''highest'', ''high'', ''medium'', ''low'', ''lowest''], got ' + str(accopt) + ' instead')
        raise Exception('ArgumentError: --alignment_accuracy argument invalid. Expected'
                        + '[''highest'', ''high'', ''medium'', ''low'', ''lowest''], got ' + str(accopt) + ' instead')

    # lower case accuracy keyword and assign to parg defaults object
    parg.align_accuracy = accopt.lower()

    # keypoint limit
    if arglist.kplim is not None:
        parg.keypointlimit = arglist.kplim

    # tiepoint limit
    if arglist.tplim is not None:
        parg.tiepointlimit = arglist.tplim

    # generic preselection
    if arglist.gen_preselect is not None:
        # convert arg to boolean
        parg.gen_preselect = str_to_bool(arglist.gen_preselect)

    # reference preselection
    if arglist.ref_preselect is not None:
        # convert arg to boolean
        parg.ref_preselect = str_to_bool(arglist.ref_preselect)
        parg.ref_preselect_option = str(arglist.ref_preselect_option)

    # align camera optimization parameters
    if arglist.al_cam is not None:
        parg.al_cam_opt_param = cam_arg_to_param_list(arglist.al_cam)

    if arglist.al_maskkeypoints is not None:
        parg.al_maskkeypoints = str_to_bool(arglist.al_maskkeypoints)

    if arglist.al_masktiepoints is not None:
        parg.al_masktiepoints = str_to_bool(arglist.al_masktiepoints)

    # -----------------Ru arguments-----------------------
    if arglist.ru:
        # set ru to true
        parg.ru = True
    # Check if any -ru options called without -ru argument
    ruargs = [arglist.ru_level, arglist.ru_cam, arglist.ru_iterate_to_ru_level, arglist.ru_cutoff, arglist.ru_increment]
    if any(ruargs) and not arglist.ru:
        # an -ru argument was called without -ru also being called, raise exception
        # print exception so it will be visible in console, then raise exception
        print(
            'ArgumentError: a -ru option was called without the --reconstruction_uncertainty argument(-ru) also being called.')
        raise Exception(
            'ArgumentError: a -ru option was called without the --reconstruction_uncertainty argument(-ru) also being called.')

    # Ru filter level
    if arglist.ru_level is not None:
        parg.ru_filt_level = arglist.ru_level

    # Ru camera optimization parameters
    if arglist.ru_cam is not None:
        parg.ru_cam_opt_param = cam_arg_to_param_list(arglist.ru_cam)

    # Ru maximum percentage cutoff
    if arglist.ru_cutoff is not None:
        parg.ru_cutoff = arglist.ru_cutoff

    # Ru increment
    if arglist.ru_increment is not None:
        parg.ru_increment = arglist.ru_increment

    # Ru iterate to Ru level
    if arglist.ru_iterate_to_ru_level is not None:
        # convert arg to boolean
        parg.ru_iterate_to_ru_level = str_to_bool(arglist.ru_iterate_to_ru_level)

    # -----------------Pa arguments-----------------------
    if arglist.pa:
        # set pa to true
        parg.pa = True
    # Check if any -pa options called without -pa argument
    paargs = [arglist.pa_level, arglist.pa_cam, arglist.pa_iterate_to_pa_level, arglist.pa_cutoff, arglist.pa_increment]
    if any(paargs) and not arglist.pa:
        # a -pa argument was called without -pa also being called, raise exception
        # print exception so it will be visible in console, then raise exception
        print(
            'ArgumentError: a -pa option was called without the --projection_accuracy argument(-pa)  also being called.')
        raise Exception(
            'ArgumentError: a -pa option was called without the --projection_accuracy argument(-pa) also being called.')

    # Pa filter level
    if arglist.pa_level is not None:
        parg.pa_filt_level = arglist.pa_level

    # Pa camera optimization parameters
    if arglist.pa_cam is not None:
        parg.pa_cam_opt_param = cam_arg_to_param_list(arglist.pa_cam)

    # Pa maximum percentage cutoff
    if arglist.pa_cutoff is not None:
        parg.pa_cutoff = arglist.pa_cutoff

    # Pa increment
    if arglist.pa_increment is not None:
        parg.pa_increment = arglist.pa_increment

    # Pa iterate to Pa level
    if arglist.pa_iterate_to_pa_level is not None:
        # convert arg to boolean
        parg.pa_iterate_to_pa_level = str_to_bool(arglist.pa_iterate_to_pa_level)

    # -----------------Re arguments-----------------------
    if arglist.re:
        # set re to true
        parg.re = True
    # Check if any -re options called without -re argument
    reargs = [arglist.re_level, arglist.re_cam, arglist.re_adapt,
              arglist.re_adapt_level, arglist.re_final_tie_point_accuracy,
              arglist.re_adapt_add_cam_param, arglist.re_fit_additional_corr,
              arglist.re_cutoff, arglist.re_increment, arglist.re_early_stop,
              arglist.re_early_stop_min_iterations, arglist.re_early_stop_variance]
    if any(reargs) and not arglist.re:
        # a -re argument was called without -re also being called, raise exception
        # print exception so it will be visible in console, then raise exception
        print(
            'ArgumentError: a -re option was called without the --reprojection_error argument(-re) also being called.')
        raise Exception(
            'ArgumentError: a -re option was called without the --reprojection_error argument(-re) also being called.')

    # Re filter level
    if arglist.re_level is not None:
        parg.re_filt_level = arglist.re_level

    # Re camera optimization parameters
    if arglist.re_cam is not None:
        parg.re_cam_opt_param = cam_arg_to_param_list(arglist.re_cam)

    # Re adapt camera enable/disable
    if arglist.re_adapt is not None:
        parg.re_adapt = str_to_bool(arglist.re_adapt)

    # Re adapt camera level
    if arglist.re_adapt_level is not None:
        parg.re_adapt_level = arglist.re_adapt_level

    # Tie point accuracy update (after Re iterations)
    if arglist.re_final_tie_point_accuracy is not None:
        parg.re_final_tie_point_accuracy = arglist.re_final_tie_point_accuracy

    # Re maximum percentage cutoff
    if arglist.re_cutoff is not None:
        parg.re_cutoff = arglist.re_cutoff

    # Re increment
    if arglist.re_increment is not None:
        parg.re_increment = arglist.re_increment

    # Re adapt camera optimization parameters
    # initialize new cam_param list, then change if called in defaults/command line args
    parg.re_adapted_cam_param = parg.re_cam_opt_param + parg.re_adapt_add_cam_param
    if arglist.re_adapt_add_cam_param is not None:
        parg.re_adapt_add_cam_param = cam_arg_to_param_list(arglist.re_adapt_add_cam_param)
        parg.re_adapted_cam_param = parg.re_cam_opt_param + parg.re_adapt_add_cam_param

    # Enable fit additional corrections
    if arglist.re_fit_additional_corr is not None:
        parg.re_fit_additional_corr = str_to_bool(arglist.re_fit_additional_corr)

    # Early stop enable/disable
    if arglist.re_early_stop is not None:
        parg.re_early_stop = str_to_bool(arglist.re_early_stop)

    if any([arglist.re_early_stop_min_iterations, arglist.re_early_stop_variance]) and not arglist.re_early_stop:
        # -re_early_stop_min_iteration or -re_early_stop_variance was called without -re_early_stop, raise exception
        # print exception so it will be visible in console, then raise exception
        print(
            'ArgumentError: -re_early_stop_min_iterations or -re_early_stop_variance was called without -re_early_stop also being called.')
        raise Exception(
            'ArgumentError: -re_early_stop_min_iterations or -re_early_stop_variance was called without -re_early_stop also being called')
    else:
        if arglist.re_early_stop_min_iterations is not None:
            parg.re_early_stop_min_iterations = arglist.re_early_stop_min_iterations
        if arglist.re_early_stop_variance is not None:
            parg.re_early_stop_variance = arglist.re_early_stop_variance


    # ---------- PARSE -LOG ARGUMENT -----------------------------------------
    if arglist.logfile is not None:
        parg.log = True
        logfilename = arglist.logfile
        if logfilename == 'default.txt':
            # Get name of document to set name of processing log.
            # Logfile will be named XXXXX_ProcessingLog.txt, where XXXXX is the name of the Metashape project.
            base = os.path.basename(doc.path)
            proclogdir = os.path.dirname(doc.path)
            proclogfile = os.path.splitext(base)[0] + "_ProcessingLog.txt"
            parg.proclogname = proclogdir + "/" + proclogfile
        else:
            # then user supplied name
            # remove quotes in string if supplied
            proclogfile = logfilename.replace('"', '').replace("'", '')
            parg.proclogname = proclogfile
    else:
        parg.log = False

    # ---------- PARSE -compute_rmse ARGUMENT ---------------------------------
    if arglist.compute_rmse is not None:
        parg.compute_rmse = str_to_bool(arglist.compute_rmse)

    # ==========================================================================

    # chunk message
    print('1. Process will be performed on chunk ' + '"' + parg.initial_chunk + '"' + '.')
    # align message
    if parg.align:
        print('2. Alignment ENABLED with the following options:\n'
              + '    -accuracy = ' + parg.align_accuracy + '\n'
              + '    -keytiepoint limit = ' + str(parg.keypointlimit) + '\n'
              + '    -tiepoint limit = ' + str(parg.tiepointlimit) + '\n'
              + '    -generic preselection = ' + str(parg.gen_preselect) + '\n'
              + '    -reference preselection = ' + str(parg.ref_preselect) + '\n'
              + '    -reference preselection mode = ' + str(parg.ref_preselect_option) + '\n'
              + '    -camera optimization parameters: ' + str(parg.al_cam_opt_param) + '\n'
              + '    -mask tie points: ' + str(parg.al_masktiepoints) + '\n'
              + '    -mask key points: ' + str(parg.al_maskkeypoints))
    else:
        print('2. Alignment DISABLED.')

    # ru message
    if parg.ru:
        print('3. Reconstruction Uncertainty gradual selection ENABLED with the following options:\n'
              + '    -Ru filter level = ' + str(parg.ru_filt_level) + '\n'
              + '    -camera optimization parameters: ' + str(parg.ru_cam_opt_param))
    else:
        print('3. Reconstruction Uncertainty gradual selection DISABLED.')

    # pa message
    if parg.pa:
        print('4. Projection Accuracy gradual selection ENABLED with the following options:\n'
              + '    -Pa filter level = ' + str(parg.pa_filt_level) + '\n'
              + '    -camera optimization parameters: ' + str(parg.pa_cam_opt_param))
    else:
        print('4. Projection Accuracy gradual selection DISABLED.')

    # re message
    if parg.re:
        print('5. Reprojection Error gradual selection ENABLED with the following options:\n'
              + '    -Re filter level = ' + str(parg.re_filt_level) + '\n'
              + '    -camera optimization parameters: ' + str(parg.re_cam_opt_param))
        if parg.re_final_tie_point_accuracy:
            print('    -tie point accuracy updated to '
                  + str(parg.re_final_tie_point_accuracy))
        if parg.re_adapt:
            print('    -adaptive camera opt. params ENABLED, when Reprojection Error below '
                  + str(parg.re_adapt_level) + ' pixels\n'
                  + '    -adapted camera opt. parameters: '
                  + str(parg.re_cam_opt_param + parg.re_adapt_add_cam_param))
        if parg.re_fit_additional_corr:
            print('    -fit additional corrections ENABLED')
        if parg.re_early_stop:
            print('    -early stop ENABLED if rmse within ' + str(parg.re_early_stop_variance)
                  + ' of target level after ' + str(parg.re_early_stop_min_iterations) + ' iterations')
    else:
        print('5. Reprojection Error gradual selection DISABLED.')

    # log message
    if parg.log:
        print('6. Log file enabled, writing to: ' + parg.proclogname + '.')
    else:
        print('6. Log file DISABLED.')

    # compute RMSE message
    if parg.compute_rmse == False:
        print('7. Computation of chunk RMSE is DISABLED.')
    else:
        print('7. Computation of chunk RMSE is ENABLED.')

    return parg


def main(parg, doc):
    """
    args:
          doc = active Metashape.app.document object
          parg = Arg object with formatted argument attributes
    """
    # first verify that project has been saved/named, stop execution if not
    if not doc.path:
        # project has not been saved. stop execution and request that user save project
        # print exception before raising exception so it will be visible in console
        print('Exception: This project has not been saved/named. Please save it before running this '
                'script. Stopping execution.')
        raise Exception('This project has not been saved/named. Please save it before running this '
                                                            'script. Stopping execution.')
    # reference active chunk
    chunk = doc.chunk

    # Initialize camera optimization parameters with all params false.
    # This will be copied and changed for use in each function
    blank_cam_opt_parameters = {'cal_f': False,
                                'cal_cx': False,
                                'cal_cy': False,
                                'cal_b1': False,
                                'cal_b2': False,
                                'cal_k1': False,
                                'cal_k2': False,
                                'cal_k3': False,
                                'cal_k4': False,
                                'cal_p1': False,
                                'cal_p2': False,
                                'fit_corrections': False
                                }

    # ====================MAIN CODE STARTS HERE====================

    # Activate different initial chunk if needed
    if not parg.initial_chunk == 'active':
        try:
            # then activate chunk
            activate_chunk(doc, parg.initial_chunk)
        except Exception as e:
            sys.exit(e)

    # ALIGN IMAGES
    if parg.align:
        try:
            # reference active chunk
            chunk = doc.chunk
            # copy active chunk, rename, make active
            align_chunk = chunk.copy()
            #align_chunk.label = chunk.label + '_Align'
            print('Copied chunk ' + chunk.label + ' to new chunk')

            # Set camera optimization parameters.
            # make a dictionary of camera opt params using arguments from parg
            al_cam_param = blank_cam_opt_parameters.copy()
            # loop through all cam parameters in parg list and set called params to True
            for elem in parg.al_cam_opt_param:
                al_cam_param['cal_{}'.format(elem)] = True

            # Run alignment using align_images function
            print('Aligning images')
            if parg.log:
                # if logging enabled use kwargs
                print('Logging to file ' + parg.proclogname)
                # write input and output chunk to log file
                with open(parg.proclogname, 'a') as f:
                    f.write("\n")
                    f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                    f.write("Copied chunk " + chunk.label + " to new chunk.\n")
                # execute function
                if parg.ref_preselect:
                    align_images(align_chunk, parg.keypointlimit, parg.tiepointlimit, al_cam_param, accuracy=parg.align_accuracy,
                                 generic_preselection=parg.gen_preselect, reference_preselection=parg.ref_preselect,
                                 reference_preselection_mode=parg.ref_preselect_option,
                                 mask_keypoints=parg.al_maskkeypoints, mask_tiepoints=parg.al_masktiepoints,
                                 compute_rmse=parg.compute_rmse,
                                 log=True, proclog=parg.proclogname)
                else:
                    align_images(align_chunk, parg.keypointlimit, parg.tiepointlimit, al_cam_param, accuracy=parg.align_accuracy,
                                 generic_preselection=parg.gen_preselect, reference_preselection=parg.ref_preselect,
                                 mask_keypoints=parg.al_maskkeypoints, mask_tiepoints=parg.al_masktiepoints,
                                 compute_rmse=parg.compute_rmse,
                                 log=True, proclog=parg.proclogname)
            else:
                if parg.ref_preselect:
                    align_images(align_chunk, parg.keypointlimit, parg.tiepointlimit, al_cam_param, accuracy=parg.align_accuracy,
                                 generic_preselection=parg.gen_preselect, reference_preselection=parg.ref_preselect,
                                 reference_preselection_mode=parg.ref_preselect_option,
                                 mask_keypoints=parg.al_maskkeypoints, mask_tiepoints=parg.al_masktiepoints,
                                 compute_rmse=parg.compute_rmse)
                else:
                    align_images(align_chunk, parg.keypointlimit, parg.tiepointlimit, al_cam_param, accuracy=parg.align_accuracy,
                                 generic_preselection=parg.gen_preselect, reference_preselection=parg.ref_preselect,
                                 mask_keypoints=parg.al_maskkeypoints, mask_tiepoints=parg.al_masktiepoints,
                                 compute_rmse=parg.compute_rmse)
            doc.save()
        except Exception as e:
            print('ERROR aligning images in ' + chunk.label + '.')
            sys.exit(e)

    # RECONSTRUCTION UNCERTAINTY
    if parg.ru:
        try:
            # reference active chunk
            chunk = doc.chunk

            # check that chunk has a point cloud
            try:
                len(chunk.tie_points.points)
            except AttributeError:
                # print exception so it will be visible in console
                print('AttributeError: Chunk "' + chunk.label + '" has no point cloud. Ensure that image '
                                                                'alignment was performed. Stopping execution.')
                raise AttributeError('Chunk "' + chunk.label + '" has no point cloud. Ensure that image alignment '
                                                               'was performed. Stopping execution.')

            # copy active chunk, rename, make active
            ru_chunk = chunk.copy()
            print('Copied chunk ' + chunk.label + ' to new chunk')

            # Set camera optimization parameters.
            # make a dictionary of camera opt params using arguments from parg
            ru_cam_param = blank_cam_opt_parameters.copy()
            # loop through all cam parameters in parg list and set called params to True
            for elem in parg.ru_cam_opt_param:
                ru_cam_param['cal_{}'.format(elem)] = True

            # Run Reconstruction Uncertainty using reconstruction_uncertainty function
            print('Running Reconstruction Uncertainty optimization')
            if parg.log:
                # if logging enabled use kwargs
                print('Logging to file ' + parg.proclogname)
                # write input and output chunk to log file
                with open(parg.proclogname, 'a') as f:
                    f.write("\n")
                    f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                    f.write("Copied chunk " + chunk.label + " to new chunk.\n")
                # execute function
                reconstruction_uncertainty(ru_chunk, parg.ru_filt_level, parg.ru_cutoff, parg.ru_increment, ru_cam_param, ru_iterate_to_ru_level=parg.ru_iterate_to_ru_level,
                                           compute_rmse=parg.compute_rmse, log=True, proclog=parg.proclogname)
            else:
                reconstruction_uncertainty(ru_chunk, parg.ru_filt_level, parg.ru_cutoff, parg.ru_increment, ru_cam_param, ru_iterate_to_ru_level=parg.ru_iterate_to_ru_level,
                                           compute_rmse=parg.compute_rmse)
            doc.save()
        except Exception as e:
            print('ERROR implenting Reconstruction Uncertainty (Ru) filter.')
            sys.exit(e)

    # PROJECTION ACCURACY
    if parg.pa:
        try:
            # reference active chunk
            chunk = doc.chunk

            # check that chunk has a point cloud
            try:
                len(chunk.tie_points.points)
            except AttributeError:
                # print exception so it will be visible in console
                print('AttributeError: Chunk "' + chunk.label + '" has no point cloud. Ensure that image '
                                                                'alignment was performed. Stopping execution.')
                raise AttributeError('Chunk "' + chunk.label + '" has no point cloud. Ensure that image alignment '
                                                               'was performed. Stopping execution.')

            # copy active chunk, rename, make active
            pa_chunk = chunk.copy()
            print('Copied chunk ' + chunk.label + ' to new chunk')

            # Set camera optimization parameters.
            # make a dictionary of camera opt params using arguments from parg
            pa_cam_param = blank_cam_opt_parameters.copy()
            # loop through all cam parameters in parg list and set called params to True
            for elem in parg.pa_cam_opt_param:
                pa_cam_param['cal_{}'.format(elem)] = True

            # Run Projection Accuracy using projection_accuracy function
            print('Running Projection Accuracy optimization')
            if parg.log:
                # if logging enabled use kwargs
                print('Logging to file ' + parg.proclogname)
                # write input and output chunk to log file
                with open(parg.proclogname, 'a') as f:
                    f.write("\n")
                    f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                    f.write("Copied chunk " + chunk.label + " to new chunk.\n")
                # execute function
                projection_accuracy(pa_chunk, parg.pa_filt_level, parg.pa_cutoff, parg.pa_increment, pa_cam_param, pa_iterate_to_pa_level=parg.pa_iterate_to_pa_level,
                                 compute_rmse=parg.compute_rmse, log=True, proclog=parg.proclogname)
            else:
                projection_accuracy(pa_chunk, parg.pa_filt_level, parg.pa_cutoff, parg.pa_increment, pa_cam_param, pa_iterate_to_pa_level=parg.pa_iterate_to_pa_level,
                                 compute_rmse=parg.compute_rmse)
            doc.save()
        except Exception as e:
            print('ERROR implenting Projection Accuracy (Pa) filter.')
            sys.exit(e)

    # REPROJECTION ERROR
    if parg.re:
        try:
            # reference active chunk
            chunk = doc.chunk

            # check that chunk has a point cloud
            try:
                len(chunk.tie_points.points)
            except AttributeError:
                # print exception so it will be visible in console
                print('AttributeError: Chunk "' + chunk.label + '" has no point cloud. Ensure that image '
                                                                'alignment was performed. Stopping execution.')
                raise AttributeError('Chunk "' + chunk.label + '" has no point cloud. Ensure that image alignment '
                                                               'was performed. Stopping execution.')

            # copy active chunk, rename, make active
            re_chunk = chunk.copy()
            print('Copied chunk ' + chunk.label + ' to new chunk')

            # Set INITIAL camera optimization parameters.
            # make a dictionary of camera opt params using arguments from parg
            re_cam_param = blank_cam_opt_parameters.copy()
            # loop through all cam parameters in parg list and set called params to True
            for elem in parg.re_cam_opt_param:
                re_cam_param['cal_{}'.format(elem)] = True

            # if re_adapt_camera, make cam_param for that also
            if parg.re_adapt:
                # make a dictionary of camera opt params using arguments from parg
                re_adapted_cam_param = blank_cam_opt_parameters.copy()
                # loop through all cam parameters in parg list and set called params to True
                for elem in parg.re_adapted_cam_param:
                    re_adapted_cam_param['cal_{}'.format(elem)] = True

            # Run Reprojection Error using reprojection_error function
            print('Running Reprojection Error optimization')

            # with logging ENABLED
            if parg.log:
                # if logging enabled use kwargs
                print('Logging to file ' + parg.proclogname)
                # write input and output chunk to log file
                with open(parg.proclogname, 'a') as f:
                    f.write("\n")
                    f.write("============= AUTO GENERATED PROCESSING LOG TEXT BELOW =============\n")
                    f.write("Copied chunk " + chunk.label + " to new chunk.\n")

                # execute function
                if parg.re_adapt:
                    # if re_adapt_cam_opt enabled, give additional kwargs
                    reprojection_error(re_chunk,
                                       parg.re_filt_level,
                                       parg.re_cutoff,
                                       parg.re_increment,
                                       re_cam_param,
                                       fit_additional_corr=parg.re_fit_additional_corr,
                                       final_tie_point_accuracy=parg.re_final_tie_point_accuracy,
                                       adapt_cam_opt=parg.re_adapt,
                                       adapt_cam_level=parg.re_adapt_level,
                                       adapt_cam_param=re_adapted_cam_param,
                                       early_stop=parg.re_early_stop,
                                       early_stop_min_iterations=parg.re_early_stop_min_iterations,
                                       early_stop_variance=parg.re_early_stop_variance,
                                       compute_rmse=parg.compute_rmse,
                                       log=True,
                                       proclog=parg.proclogname
                                       )
                else:
                    # if re_adapt_cam_opt disabled, leave kwargs out of function call
                    reprojection_error(re_chunk,
                                       parg.re_filt_level,
                                       parg.re_cutoff,
                                       parg.re_increment,
                                       re_cam_param,
                                       fit_additional_corr=parg.re_fit_additional_corr,
                                       final_tie_point_accuracy=parg.re_final_tie_point_accuracy,
                                       early_stop=parg.re_early_stop,
                                       early_stop_min_iterations=parg.re_early_stop_min_iterations,
                                       early_stop_variance=parg.re_early_stop_variance,
                                       compute_rmse=parg.compute_rmse,
                                       log=True,
                                       proclog=parg.proclogname
                                       )
            else:
                if parg.re_adapt:
                    # if re_adapt_cam_opt enabled, give additional kwargs
                    reprojection_error(re_chunk,
                                       parg.re_filt_level,
                                       parg.re_cutoff,
                                       parg.re_increment,
                                       re_cam_param,
                                       fit_additional_corr=parg.re_fit_additional_corr,
                                       final_tie_point_accuracy=parg.re_final_tie_point_accuracy,
                                       adapt_cam_opt=parg.re_adapt,
                                       adapt_cam_level=parg.re_adapt_level,
                                       adapt_cam_param=re_adapted_cam_param,
                                       early_stop=parg.re_early_stop,
                                       early_stop_min_iterations=parg.re_early_stop_min_iterations,
                                       early_stop_variance=parg.re_early_stop_variance,
                                       compute_rmse=parg.compute_rmse
                                       )
                else:
                    # if re_adapt_cam_opt disabled, leave kwargs out of function call
                    reprojection_error(re_chunk,
                                       parg.re_filt_level,
                                       parg.re_cutoff,
                                       parg.re_increment,
                                       re_cam_param,
                                       fit_additional_corr=parg.re_fit_additional_corr,
                                       final_tie_point_accuracy=parg.re_final_tie_point_accuracy,
                                       early_stop=parg.re_early_stop,
                                       early_stop_min_iterations=parg.re_early_stop_min_iterations,
                                       early_stop_variance=parg.re_early_stop_variance,
                                       compute_rmse=parg.compute_rmse
                                       )

            doc.save()
        except Exception as e:
            print('ERROR implenting Reconstruction Error (Re) filter.')
            sys.exit(e)

    #At completion of script print a list of all arguments used so user can verify
    print('=====================================================')
    print('   Script completed using the following arguments:  ')
    print('=====================================================')
    for key, value in sorted(parg.__dict__.items()):
        print(key, '=', value)


# execute main() if script call
if __name__ == '__main__':
    # initialize a default arguments object pre-populated with the default arguments above
    defaults = Args()
    # reference active document
    doc_obj = Metashape.app.document
    # get command line arguments
    parg_obj = parse_command_line_args(defaults, doc_obj)
    # run main
    main(parg_obj, doc_obj)

## use this block for debugging (comment main() above)
#    # Get confirmation from user to continue
#    conf = True
#    msg = '\n\nDo you want to continue with the options printed above?'
#    conf = input("%s (y/N) " % msg).lower() == 'y'
##    conf = Metashape.app.getBool(label='Do you want to continue?')
#
#    if conf:
#        # run main
#        main(parg_obj, doc_obj)
#    else:
#        print('\nStopping execution.')
