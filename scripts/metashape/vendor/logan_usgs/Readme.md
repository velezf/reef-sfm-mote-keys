## Agisoft Metashape/Photoscan Automated Image Alignment and Error Reduction version 2.0

```
Align_RuPaRe_v2_Metashape.py
```

This repository contains python scripts which automate image alignment and sparse point cloud error reduction in the [Agisoft Metashape/Photoscan](https://www.agisoft.com/) structure from motion photogrammetry software package using the [Agisoft Metashape Python API.](https://www.agisoft.com/pdf/metashape_python_api_1_8_0.pdf) 

The current version of the script (version 2.0) approximates the workflow described in U.S. Geological Survey Open-File Report 2021-1039 [(Over et al., 2021)](https://www.doi.org/10.3133/ofr20211039). The workflow involves the application of gradual selection filters to reduce errors in sparse point clouds, and improve camera lens models and camera position estimates. The error reduction technique and sparse point cloud gradual selection filter values were developed with the goal of maintaining the accuracies of traditional photogrammetric processes with newer techniques supported by structure from motion (SfM) based software. Legacy versions of this script which implement a previous version (version 1.0) of the workflow are available in the legacy_scripts directory within this repository.

The script allows users to align imagery and apply different gradual selection filters to reduce errors in sparse point clouds. After initial image alignment, two filters (Reconstruction Uncertainty [Ru], and Projection Accuracy [Pa]) are applied sequentially to a point cloud with camera optimization performed after each filter. Although initial target filter values can be supplied by the user, the final filter values will be determined by the value required to select a pre-defined percentage of the sparse points. The default is for each filter to select 50% of the sparse points, but this percentage can be changed by the user. Once the required percentage of sparse points is selected, the points are deleted and camera optimization is performed. The third filter, Reprojection Error (Re), is applied in an iterative fashion such that only a fraction (default is 10%) of the total sparse points is selected and deleted within an iteration. Camera optimization is performed between each iteration to improve the camera lens model using the newly filtered subset of higher-quality sparse point matches. These iterations continue until a user-defined RMS Reprojection Error level is achieved (default is 0.3). Once all of the points exceeding this threshold have been deleted, the tie point accuracy is optionally adjusted to a user-defined level (default final tie point accuracy is 0.3) and camera optimization is performed a final time with the "fit additional parameters" option enabled. 

Although the default filter levels and iteration behavior for each filter is set to follow the workflow described in Over et al. (2021), the user can deviate from this workflow using command line arguments or by changing the hardcoded ‘defaults’ object at the beginning of the script in lines 246-324. For instance, if the user wishes to ensure that all remaining sparse points satisfy a specific Reconstruction Uncertainty (Ru) or Projection Accuracy (Pa) level, these filters can be run iteratively to delete points until the required filter level is met (similar to the previous version of this workflow found in the legacy scripts - see the fourth example in the "Example commands, from Metashape console" section). **The default workflow performed by this script, and the suggested filter levels may not be appropriate for all imagery and projects; use caution if accepting these defaults.**

Guidance on how to set the filter levels and more about the default workflow can be found in [Over et al. (2021).](https://www.doi.org/10.3133/ofr20211039) 

___

### Compatibility

The current version of this script (version 2.0) has been developed and tested for Agisoft Metashape version 1.6 through 1.8

Scripts that implement a previous version of this workflow (version 1.0) are available for Agisoft Metashape 1.5 and 1.6, and Agisoft Photoscan 1.4 in the [legacy_scripts](./legacy_scripts) directory within this repository.

___

### Details

The script runs in the following sequence (only those tasks specified by the user in the command line are run):

1. **Image Alignment** `-align, --align_images`:  Image alignment is performed on the chunk specified with the `-chunk` argument [default = active chunk].  Camera optimization is performed after image alignment. The user can provide the following optional arguments (*if any of these arguments are called the `-align` argument must also be present in the command line*):
    - `-al_kplim, --align_keypointlimit = integer [default = 60,000]`: Key point limit
    - `-al_tplim, --align_tiepointlimit = integer [default = 0 (unlimited)]`: Tie point limit
    - `-al_accuracy, --alignment_accuracy [highest, high, medium, low, lowest][default = high]`: Alignment accuracy
    - `-al_generic, --align_generic_preselection = boolean [default = True]`: Enable generic preselection
    - `-al_reference, --align_reference_preselection = boolean [default = True]`: Enable reference preselection
    - `-al_reference_mode, --align_reference_preselection_mode [Source, Estimated, Sequential][default = Source]`: Reference preselection mode
    - `-al_cam_param, --align_camera_opt_param = list of camera params [default = f, cx, cy, k1, k2, k3, p1, p2]`: Parameters for camera optimization
    - `-al_masktiepoints, --al_masktiepoints = boolean [default = False]`: Mask tie points
    - `-al_maskkeypoints, --al_maskkeypoints = boolean [default = False]`: Mask key points
    <br>
    
2. **Reconstruction Uncertainty (Ru)** gradual selection filter `-ru, --reconstruction_uncertainty`: This operation is performed on the  active chunk created by the `-align` operation, or the chunk specified with the `-chunk [default = active chunk]` argument. Running the script with the `-ru` defaults will run one iteration of the reconstruction uncertainty filter, with no more than a specified percentage (`-ru_max_percentage_delete [default 50%]`) of the sparse points removed in a single iteration. Camera optimization is performed after each iteration. A target reconstruction uncertainty filter level (`-ru_level`) can be supplied, however the final reconstruction uncertainty level may be higher than this target value, and will be determined by the filter level required to delete the specified percentage of points. The filter can be run iteratively using the `-ru_iterate_to_ru_level` argument. If this option is used, the filter will iterate and delete the specified percentage of points until all remaining points satisfy the target reconstruction uncertainty level. The user can provide an optional target reconstruction uncertainty level `-ru_level 12`. If no argument is provided, `-ru` will use a default value [default = 10]. The user can provide the following optional arguments (*if any of these arguments are called the `-ru` argument must also be present in the command line*):
    - `-ru_level, --reconstruction_uncertainty_level = float [default = 10]`: Target reconstruction uncertainty level
    - `-ru_cam_param, --reconstruction_uncertainty_camera_opt_param = list of camera params [default = f, cx, cy, k1, k2, k3, p1, p2]`: Parameters for camera optimization
    <br>

    &nbsp;&nbsp;&nbsp;&nbsp; *---- **IMPORTANT:** Changing the Reconstruction Uncertainty arguments below will deviate from the workflow decribed in Open-File Report 2021-1039 ----*
    - `-ru_iterate_to_ru_level, --reconstruction_uncertainty_iterate_to_ru_level = boolean [default = False]`: Enables or disables multiple Ru gradual selection iterations until specified Ru level is met
    - `-ru_max_percentage_delete, --reconstruction_uncertainty_max_percentage_delete = float [default = 0.5]`: Maximum percentage (0-1) of points to select and delete during each Ru iteration
    - `-ru_increment, --reconstruction_uncertainty_increment = float [default = 0.1]`: Gradual selection value to use for incremental selection of points for deletion (increasing this value will decrease execution time, but may also decrease accuracy of filter levels used)
    <br>
    
3. **Projection Accuracy (Pa)** gradual selection filter `-pa, --projection_accuracy`: This operation is performed on the  active chunk created by the `-ru` operation, or the chunk specified with the `-chunk [default = active chunk]` argument. Running the script with the `-pa` defaults will run one iteration of the projection accuracy filter, with no more than a specified percentage (`-pa_max_percentage_delete [default 50%]`) of the sparse points removed in a single iteration. Camera optimization is performed after each iteration. A target projection accuracy filter level (`-pa_level`) can be supplied, however the final projection accuracy level may be higher than this target value, and will be determined by the filter level required to delete the specified percentage of points. The filter can be run iteratively using the `-pa_iterate_to_pa_level` argument. If this option is used, the filter will iterate and delete the specified percentage of points until all remaining points satisfy the target projection accuracy level. The user can provide an optional target projection accuracy level `-pa_level 4`. If no argument is provided, `-pa` will use a default value [default = 3]. The user can provide the following optional arguments (*if any of these arguments are called the `-pa` argument must also be present in the command line*):
    - `-pa_level, --projection_accuracy_level = float [default = 3]`: Target projection accuracy level
    - `-pa_cam_param, --projection_accuracy_camera_opt_param = list of camera params [default = f, cx, cy, k1, k2, k3, p1, p2]`: Parameters for camera optimization
    <br>

    &nbsp;&nbsp;&nbsp;&nbsp; *---- **IMPORTANT:** Changing the Projection Accuracy arguments below will deviate from the workflow decribed in Open-File Report 2021-1039 ----*
    - `-pa_iterate_to_pa_level, --projection_accuracy_iterate_to_pa_level = boolean [default = False]`: Enables or disables multiple Pa gradual selection iterations until specified Pa level is met
    - `-pa_max_percentage_delete, --projection_accuracy_max_percentage_delete = float [default = 0.5]`: Maximum percentage (0-1) of points to select and delete during each Pa iteration
    - `-pa_increment, --projection_accuracy_increment = float [default = 0.01]`: Gradual selection value to use for incremental selection of points for deletion (increasing this value will decrease execution time, but may also decrease accuracy of filter levels used)
    <br>

4. **Reprojection Error (Re)** gradual selection filter `-re, --reprojection_error`: This operation is performed on the  active chunk created by the `-pa` operation, or the chunk specified with the `-chunk [default = active chunk]` argument. Running the script with the `-re` defaults will run the filter iteratively until all remaining points in the sparse point cloud satisfy the target RMS reprojection error level (`-re_level [default 0.3]`). During each iteration, the reprojection error filter level used will be determined by the filter level required to select and delete a specified percentage of points (`-re_max_percentage_delete [default 0.1, (10%)]`). Camera optimization is performed after each iteration. After the final iteration if the reprojection error filter is at or below the target RMS reprojection error level, the tie point accuracy is adjusted (`-re_final_tie_point_accuracy [default = 0.3]`) and camera optimization is performed a final time with “fit additional correction” enabled (`-re_fit_additional_corr [default = True]`). Additional camera parameters can be introduced based on the current-iteration reprojection error level using the `-re_adapt_cam [default = False]` argument, although this deviates from the default workflow of the script. The user can provide an optional target reprojection error level `-re_level 0.4`. If no argument is provided, `-re` will use a default value [default = 0.3]. Note that the reprojection error reduction sequence implemented in this script only performs steps 1 - 8, and step 15 of the workflow outlined on page 28 in U.S. Geological Survey Open-File Report 2021-1039 [(Over et al., 2021)](https://www.doi.org/10.3133/ofr20211039). If the user wishes to complete that workflow exactly as described, the error reduction sequence must be completed outside of this script. If the user wishes to change the default behavior or values used by the reprojection error reduction function in this script the following optional arguments can be provided (*if any of these arguments are called the `-re` argument must also be present in the command line*):
    - `-re_level, --reprojection_error_level = float [default = 0.3]`: Target reprojection error level
    - `-re_cam_param, --reprojection_error_camera_opt_param = list of camera params [default = f, cx, cy, k1, k2, k3, p1, p2]`: Parameters for camera optimization
    <br>

    &nbsp;&nbsp;&nbsp;&nbsp; *---- **IMPORTANT:** Changing the Reprojection Error arguments below will deviate from steps 1-8, and step 15 of the workflow decribed in Open-File Report 2021-1039 ----*

    - `-re_adapt_cam, --reprojection_error_adaptive_cam = boolean [default = False]`: Enables or disables introducing additional camera parameters if Re level falls below a set level (pixels)
    - `-re_adapt_level, --reprojection_error_adaptive_cam_level [default = 1]`: Re level below which to enable additional camera parameters
    - `-re_adapt_cam_param, --reprojection_error_adapt_camera_param = list of camera params [default = k4, b1, b2]`: Additional camera parameters to be enabled if Re level falls below `-re_adapt_level`
    - `-re_fit_additional_corr, --reprojection_error_fit_additional_corr = boolean [default = True]`: Enable "Fit Additional Parameters" during final camera optimization after Re filtering is complete
    - `re_final_tie_point_accuracy, --reprojection_error_final_tie_point_accuracy = float [default = 0.3]`: Tie point accuracy set to this value during final camera optimization after Re filtering is complete
    - `-re_max_percentage_delete, --reprojection_error_max_percentage_delete = float [default = 0.1]`: Maximum percentage (0-1) of points to select and delete during each Re iteration
    - `-re_increment, --reprojection_error_increment = float [default = 0.01]`: Gradual selection value to use for incremental selection of points for deletion (increasing this value will decrease execution time, but may also decrease accuracy of filter levels used)
    - `-re_early_stop, --reprojection_error_early_stop = boolean [default = False]`: Option to prevent excessive iterations of the Re filter in cases where continuing iterations select a very small percentage of points. With this option enabled, iterations will be stopped once a minumum number of iterations have occurred (set with `-re_early_stop_min_iterations`), and the Re filter level is within a set range of the target Re filter level (set with `-re_early_stop_variance`).
    - `-re_early_stop_min_iterations, --reprojection_error_early_stop_min_iterations [default = 5]`: Minimum number of iterations to run before activation of Re early stop.
    - `-re_early_stop_variance, --reprojection_error_early_stop_variance [default = 0.005]`: Allowed variance from target filter level(-re_level) for activation of Re early stop.
    <br>

5. **Additional arguments:**
    - `-chunk [default: ACTIVE chunk]`: optional argument to specify which chunk will be initially used by the script. If this argument is not provided, the script will use the currently active chunk by default.
    - `-log [default: DISABLED]`: optional argument to create a processing log file. If called with no file name (`-log`), the default name of the file will be "XXXX_ProcessingLog.txt" (where XXXX is the name of Metashape project). The default location is the directory where the Metashape project resides. A different name can be specified for the file using the command line argument `-log myProcessingLogile.txt`. The log file can be manually edited between script executions; repeated script executions will append additional process logs to the end of the file.
    - `-compute_rmse [default = True (ENABLED)]`: Optional argument to prevent the script from computing chunk RMSE. The computation of the chunk RMSE using the `compute_RMSE` function is computationally intensive and can be slow for projects with a large number of points in the sparse point cloud. Although disabling the chunk RMSE computation (`-compute_rmse=False`) deviates from the workflow decribed in Open-File Report 2021-1039, this can significantly reduce processing time for large projects. If RMSE computation is disabled, the chunk RMSE will be set to a value of -9999 in the console messages and the log file for the image alignment (`-align`), Reconstruction Uncertainty (`-ru`), Projection Accuracy (`-pa`), and Reprojection Error (`-re`) gradual selection steps. For the image alignment, Ru and Pa steps, there is no functional difference with this option except for the RMSE values provided in the console and the processing log. For the Re step, disabling RMSE computation will cause the gradual selection filter to continue until all points satisfy the target Re filter level value (instead of until the chunk RMSE falls to the target Re filter level).

For each processing step, a new chunk is created in the Metashape project. The chunk is labeled with the name of the initial chunk, plus a suffix designating the process that was run. For instance, `run Align_RuPaRe_v2_Metashape.py -chunk myInitialChunk -align -ru -ru_level 15 -pa -pa_level 4`, will create three new chunks in the project labeled (where XX is the final filter value):
   - "myInitialChunk_Align" 
   - "myInitialChunk_Align_RuXX"  
   - "myInitialChunk_Align_RuXX_PaXX" 

___

### Installation
The script does NOT need to be in any specific folder or directory.

#### Dependencies
The script is completely self-contained and does not require any external Python or other libraries beyond those already installed and accessible when Agisoft Metashape is installed on your system. It does not reference or access any URL or external resources beyond those used by Agisoft Metashape.

### Usage
The script can be run from three places within Metashape:

1. **The Metashape python console**, using `run Align_RuPaRe_v2_Metashape.py`. This is the preferred method. However, when the script is run from the python console, certain exceptions are not shown the user (i.e. when certain errors are encountered, the code may be interrupted and the user will not be shown any error warnings).
2. **The “Run Script” dialog box**. All command line argument can be entered in the dialog box. Any exceptions raised by python will be shown to the user in a separate dialog box. *(Note: the -h,--help usage message cannot be displayed if the script is being run from the "Run Script" dialog box)*
3. **The "Batch processing" dialog box**. If the script is run as part of a batch process using the "Batch processing" dialog box, it is recommended to use the `-chunk` argument to specify which chunk the script will use. The drop down menu and check boxes enabling or disabling chunks in the "Batch processing" dialog box are not referenced by the script.

### Example commands, from Metashape console

- ```run Align_RuPaRe_v2_Metashape.py -align -ru -pa -re -log``` 
    
    &nbsp;&nbsp; *Default workflow decribed by U.S. Geological Survey Open-File Report 2021-1039 [(Over et al., 2021).](https://www.doi.org/10.3133/ofr20211039)*
    1. align ACTIVE chunk with default accuracy [high], default key point limit [60,000], default tie point limit [0, unlimited], generic preselection enabled [default], reference preselection enabled [default], and optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2].
    2. run Reconstruction Uncertainty (Ru) gradual selection once on results of alignment with default target Ru level [10]; final Ru filter level will be determined by value needed to select and delete 50% of sparse points. After points are deleted, optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Final Ru filter level may be higher than target value; chunk will be named with final Ru filter level.
    3. run Projection Accuracy (Pa) gradual selection once on results of Ru with default target Pa filter level [3]; final Pa filter level will be determined by value needed to select and delete 50% of sparse points. After points are deleted, optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Final Pa filter level may be higher than target value; chunk will be named with final Pa filter level.
    4. run Reprojection Error (Re) gradual selection on results of Pa with default filter level [0.3]. Re filter will run interatively, selecting and deleting 10% of the remaining sparse points during each iteration. Camera optimization will run after each iteration with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Camera optimization parameters will not change based on Re level [default]. After all Re iterations are complete, tie point accuracy will be set to 0.3 [default] and camera optimization will be performed a final time with "fit additional corrections" enabled [default].
    5. log results to default log text file in Metashape project folder.
    <br>
    
- ```run Align_RuPaRe_v2_Metashape.py -align -al_accuracy highest -al_kplim 0 -ru -ru_level 15 -pa -pa_level 4.5 -log```
    1. align ACTIVE chunk with accuracy = "highest", key point limit [0, unlimited], default tie point limit [0, unlimited], generic preselection enabled [default], reference preselection enabled [default], and optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2].
    2. run Reconstruction Uncertainty (Ru) gradual selection once on results of alignment with target Ru level [15]; final Ru filter level will be determined by value needed to select and delete 50% of sparse points. After points are deleted, optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Final Ru filter level may be higher than target value; chunk will be named with final Ru filter level.
    3. run Projection Accuracy (Pa) gradual selection once on results of Ru with target Pa filter level [4.5]; final Pa filter level will be determined by value needed to select and delete 50% of sparse points. After points are deleted, optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Final Pa filter level may be higher than target value; chunk will be named with final Pa filter level.
    4. log results to default log text file in Metashape project folder.
    <br>
    
- ```run Align_RuPaRe_v2_Metashape.py -chunk myChunk -ru -ru_max_percentage_delete 0.25 -pa```
    1. run Reconstruction Uncertainty (Ru) gradual selection once on previously aligned chunk named "myChunk" with target Ru level [10]; final Ru filter level will be determined by value needed to select and delete 25% of sparse points. After points are deleted, optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Final Ru filter level may be higher than target value; chunk will be named with final Ru filter level.
    2. run Projection Accuracy (Pa) gradual selection once on results of Ru with default target Pa filter level [3]; final Pa filter level will be determined by value needed to select and delete 50% of sparse points. After points are deleted, optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Final Pa filter level may be higher than target value; chunk will be named with final Pa filter level.
    3. do not log results to a log file.
    <br>

- ```run Align_RuPaRe_v2_Metashape.py -align -al_kplim 0 -ru -ru_level 10 -ru_iterate_to_ru_level=True -ru_max_percentage_delete 0.25 -pa -pa_level 3 -pa_iterate_to_pa_level=True -pa_max_percentage_delete 0.5 -re -re_level 0.3 -re_adapt_cam=True -re_fit_additional_corr=False -log myLogFile.txt```

    &nbsp;&nbsp; *SIMILAR TO VERSION 1.0 WORKFLOWS CONTRAINED IN LEGACY SCRIPTS*
    1. align ACTIVE chunk with default accuracy [high], key point limit [0, unlimited], default tie point limit [0, unlimited], generic preselection enabled [default], reference preselection enabled [default], and optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2].
    2. run Reconstruction Uncertainty (Ru) gradual selection iteratively on results of alignment with target Ru filter level [10]. For each iteration Ru filter level is set to the value necessary to only delete 25% of the sparse points. Optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2] after each filter iteration. Filter iterations will continue until all sparse points satisfy Ru level 10.
    3. run Projection Accuracy (Pa) gradual selection iteratively on results of Ru filter with target Pa filter level [3]. For each iteration the Pa filter level is set to the value necessary to only delete 50% of the sparse points. Optimize cameras with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2] after each filter iteration. Filter iterations will continue until all sparse points satisfy Pa level 3.
    4. run Reprojection Error (Re) gradual selection iteratively on results of Pa with default filter level [0.3]. For each iteration the Re filter level is set to the value necessary to only delete 10% of the sparse points. Camera optimization will run after each iteration with default camera optimization parameters [f, cx, cy, k1, k2, k3, p1, p2]. Once Re level falls below 1 pixel, additional camera optimization parameters [k4, b1, b2] will be added. Tie point accuracy will not be adjusted. Filter iterations will continue until all sparse points satisfy Re level 0.3.
    5. log results to default log text file in Metashape project folder.
    <br>

- ```run Align_RuPaRe_v2_Metashape.py -chunk myChunk -re -re_level 0.4 -re_increment 0.3 -re_cam_param f, cx, cy, k1, k2, k3 -re_fit_additional_corrections=True -re_final_tie_point_accuracy 0.1 -log```
    1. run Reprojection Error (Re) gradual selection on chunk "myChunk" with target Re filter level [0.4]. Re filter will run interatively, selecting and deleting 10% of the remaining sparse points during each iteration. During determination of Re value required to select 10% of points, filter value will be incremented by 0.3. Camera optimization will run after each iteration with camera optimization parameters [f, cx, cy, k1, k2, k3]. Camera optimization parameters will not change based on Re level [default]. After all Re iterations are complete, tie point accuracy will be set to [0.1] and camera optimization will be performed a final time with "fit additional corrections" enabled [default].
    2. log results to default log text file in Metashape project folder.
    <br>

- ```run Align_RuPaRe_v2_Metashape.py -chunk myChunk -re -re_level 0.4 -re_early_stop=True -re_early_stop_max_iterations 10 -re_early_stop_variance 0.009 -log```
    1. run Reprojection Error (Re) gradual selection on chunk "myChunk" with target Re filter level [0.4]. Re filter will run interatively, selecting and deleting 10% of the remaining sparse points during each iteration. Re filtering will be allowed to stop early after a minimum of 10 iterations, if Re filter level value is within 0.009 of target level. Camera optimization parameters will not change based on Re level [default]. After all Re iterations are complete, tie point accuracy will be set to [0.1] and camera optimization will be performed a final time with "fit additional corrections" enabled [default].
    2. log results to default log text file in Metashape project folder.
    <br>

- ```run Align_RuPaRe_v2_Metashape.py -align -ru -pa -re -compute_rmse=False -log``` 

    &nbsp;&nbsp; *For a large project in which the computation of the chunk RMSE causes the script to run very slowly, the RMSE computation can be disabled*
    1. run image alignment, and Ru, Pa and Re gradual selection operations using default arguments, but do not compute chunk RMSE for console messages or log file (this is useful to speed up the script on large projects).
    2. for Reprojection Error gradual selection do not use chunk RMSE as iteration criteria for completing Reprojection Error filtering iterations. Instead use Reprojection Error filter level as criteria for stopping iterations.
    3. log results to default log text file in Metashape project folder.
    <br>

- ```run Align_RuPaRe_v2_Metashape.py -chunk myRuPaChunk -compute_rmse=False -re -re_early_stop=True -re_early_stop_min_iterations 2 -re_early_stop_variance 10000 -re_final_tie_point_accuracy 1.0 -log``` 

    &nbsp;&nbsp; *To run Reprojection Error (Re) iterations only twice and stop regardless of the final Re filter level*
    1. run Re gradual selection operation on chunk "myRuPaChunk" using default arguments, but do not compute chunk RMSE (this is useful to speed up the script on large projects). Stop Re gradual selection after two iterations if the final Re filter level is within 10000 of the target Re filter level [default Re filter level = 0.3]. Using a very large number (10000) for `re_early_stop_variance` will cause this condition to always be met, and will effectively cause the iterations to stop after the specified number of iterations regardless of the final filter value.
    2. after all Re iterations are complete, tie point accuracy will be left at [1.0] (instead of being set to the default value of [0.1]) and camera optimization will be performed a final time with "fit additional corrections" enabled [default].
    3. log results to default log text file in Metashape project folder.
    <br>
    
___

### Using functions directly in Metashape console or another script

The functions in the script can be used directly in the Metashape console, or in another script by importing as a module:

```
import sys
import Metashape
sys.path.append('C:\path_to_directory_with_Align_RuPaRe_v2_Metashape')
from Align_RuPaRe_v2_Metashape import (
                                        activate_chunk, 
                                        align_images, 
                                        reconstruction_uncertainty, 
                                        projection_accuracy, 
                                        reprojection_error
                                        )
doc = Metashape.app.document
#dictionary of booleans for camera lens parameters for camera optimization
cam_opt_parameters = {'cal_f': True, 'cal_cx': True, 'cal_cy': True, 
                        'cal_b1': False, 'cal_b2': False, 
                        'cal_k1': True, 'cal_k2': True, 'cal_k3': True, 'cal_k4': False,
                        'cal_p1': True, 'cal_p2': True
                      }  
#activate chunk
chunk = activate_chunk(doc, 'mychunk')
#run reconstruction uncertainty error reduction
reconstruction_uncertainty(chunk, 10, 0.25, 1, cam_opt_parameters, log=True, proclog='my_log_file.txt')
```
___

### Defaults

The following default values are used:
- `--align_images`:
  - keypointlimit: **60,000** (set with argument, `-al_kplim x`, where x is an integer)
  - tiepointlimit: **0** (set with argument, `-al_tplim x`, where x is an integer)
  - generic_preselection: **ENABLED** (set with argument, `-al_generic [True, False]`)
  - reference_preselection: **ENABLED** (set with  argument, `-al_reference [True, False]`)
  - reference_preselection_mode: **Source** (set with argument, `-al_reference_mode [source, estimated, sequential]`)
  - alignment_accuracy: **High** (set with argument, `-al_accuracy [highest, high, medium, low, lowest]`)
  - camera optimization parameters: f, cx, cy, k1, k2, k3, p1, p2 (set with argument, `-al_cam_param  list`, where list is a space or comma delimited list of parameters)
  - mask_tiepoints: **False** (set with  argument, `-al_masktiepoints [True, False]`)
  - mask_keypoints: **False** (set with  argument, `-al_maskkeypoints [True, False]`)
- `--reconstruction_uncertainty`:
  - target reconstruction uncertainty gradual selection filter level: **10.0** (can be set with argument `-ru_level x`, where x is a floating point value)
  - camera optimization parameters: f, cx, cy, k1, k2, k3, p1, p2 (set with argument, `-ru_cam_param list`, where list is a space or comma delimited list of parameters)
  - iterate filter until Ru level = target Ru level (-ru_level): **False** (set with argument, `-ru_iterate_to_ru_level [True, False]`)
  - maximum percentage of points to delete during each Ru iteration: **0.5** (set with argument, `-ru_max_percentage_delete x`, where x is a floating point value between 0 to 1)
  - gradual selection value to use for incremental selection of points in Ru filtering: **0.1** (set with argument, `-ru_increment x`, where x is a floating point value)
- `--projection_accuracy`:
  - target projection accuracy gradual selection filter level: **3.0** (can be set with argument `-pa_level x`, where x is a floating point value)
  - camera optimization parameters: f, cx, cy, k1, k2, k3, p1, p2 (set with argument, `-pa_cam_param list`, where list is a space or comma delimited list of parameters)
  - iterate filter until Pa level = target Pa level (-pa_level): **False** (set with argument, `-pa_iterate_to_pa_level [True, False]`)
  - maximum percentage of points to delete during each Pa iteration: **0.5** (set with argument, `-pa_max_percentage_delete x`, where x is a floating point value between 0 to 1)
  - gradual selection value to use for incremental selection of points in Pa filtering: **0.1** (set with argument, `-pa_increment x`, where x is a floating point value)
- `--reprojection_error`:
  - target reprojection error gradual selection filter level: **0.3** (can be set with argument `-re_level x`, where x is a floating point value)
  - camera optimization parameters (adaptive): 
      - if adaptive cam parameters disabled using `-re_adapt_cam False` or no argument provided [default=False]:
           - f, cx, cy, k1, k2, k3,  p1, p2 (set with argument `-re_cam_param list`, where list is a space or comma delimited list of parameters)
      - if adaptive cam parameters enabled using `-re_adapt_cam=True`:
           - f, cx, cy, k1, k2, k3,  p1, p2 (set with argument `-re_cam_param list`, where list is a space or comma delimited list of parameters)
           - when Re filter level < 1 pixel (set with argument `-re_adapt_level`) additional parameters are included: f, cx, cy, k1, k2, k3, **k4**, **b1**, **b2**, p1, p2 (additional parameters set with argument `-re_adapt_cam_param list`)
  - Fit additional correction during final camera optimization: **True** (can be set with `-re_fit_additional_corr [True, False]`. If enabled, then camera optimization is performed one final time after Re filter iterations are complete, with "Fit Additional Parameters" enabled.
  - Final tie point accuracy set during final camera optimization: **0.3** (can be set with `-re_final_tie_point_accuracy x` where x is a floating point value). Tie point accuracy is only used if, `-re_fit_additional_corr=True`
  - gradual selection value to use for incremental selection of points in Re filtering: **0.01** (set with argument, `-re_increment x`, where x is a floating point value)
- `--compute_rmse`: **ENABLED** (can be DISABLED to improve computation time for large projects using `-compute_rmse=False`)

___

### Contacts

This script was developed at the United States Geological Survey, Pacific Coastal and Marine Science Center, Santa Cruz, CA (https://www.usgs.gov/centers/pcmsc/science/remote-sensing-coastal-change). For questions related to the script contact:

Joshua Logan, [jlogan@usgs.gov](jlogan@usgs.gov)

Andy Ritchie, [aritchie@usgs.gov](aritchie@usgs.gov)

Phil Wernette [pwernette@usgs.gov](pwernette@usgs.gov)

___

### Suggested Citation
Logan, J.B., Wernette, P.A. and Ritchie, A.C., 2022, Agisoft Metashape/Photoscan Automated Image Alignment and Error Reduction version 2.0: U.S. Geological Survey code repository, U.S. Geological Survey software release, python package, Reston, Va., (https://doi.org/10.5066/P9DGS5B9).

___

### Updates
No future updates to this script are planned at this time.

___

### References

Over, J.R., A.C. Ritchie, C. Kranenburg, J.A. Brown, D.D. Buscombe, T. Noble, C.R. Sherwood, J. Warrick, and P.A. Wernette. (2021) Processing coastal imagery with Agisoft Metashape Professional Edition, version 1.6—Structure from motion workflow documentation: U.S. Geological Survey Open-File Report 2021-1039, x p. [doi.org/10.3133/ofr20211039.](https://www.doi.org/10.3133/ofr20211039)

