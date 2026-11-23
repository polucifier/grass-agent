---
name: r.viewshed
description: Computes the viewshed of a point on an elevation raster map.
keywords: [ raster, viewshed ]
---

# r.viewshed

Computes the viewshed of a point on an elevation raster map.

=== "Command line"

    **r.viewshed**
    [**-crbe**]
    **input**=*name*
    **output**=*name*
    **coordinates**=*east,north*
    [**observer_elevation**=*value*]
    [**target_elevation**=*value*]
    [**max_distance**=*value*]
    [**--overwrite**]

    Example:

    ```sh
    r.viewshed input=name output=name coordinates=0.0
    ```

=== "Python (grass.tools)"

    *grass.tools.Tools.r_viewshed*(**input**,
        **output**,
        **coordinates**,
        **observer_elevation**=*1.75*,
        **target_elevation**=*0.0*,
        **max_distance**=*-1*,
        **flags**=*None*,
        **overwrite**=*None*,
        **verbose**=*None*,
        **quiet**=*None*,
        **superquiet**=*None*)

    Example:

    ```python
    tools = Tools()
    tools.r_viewshed(input="name", output="name", coordinates="0,0")
    ```

=== "Python (grass.script)"

    *grass.script.run_command*("***r.viewshed***",
        **input**,
        **output**)

## Parameters

=== "Command line"

    **input**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of input elevation raster map  
    **output**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name for output raster map  
    **coordinates**=*east,north* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Coordinates of viewing position  
    **observer_elevation**=*value*  
    &nbsp;&nbsp;&nbsp;&nbsp;Viewing elevation above the ground  
    &nbsp;&nbsp;&nbsp;&nbsp;Default: *1.75*  
    **target_elevation**=*value*  
    &nbsp;&nbsp;&nbsp;&nbsp;Offset for target elevation above the ground  
    &nbsp;&nbsp;&nbsp;&nbsp;Default: *0.0*  
    **max_distance**=*value*  
    &nbsp;&nbsp;&nbsp;&nbsp;Maximum visibility radius. By default infinity (-1)  
    &nbsp;&nbsp;&nbsp;&nbsp;Default: *-1*  
    **-b**  
    &nbsp;&nbsp;&nbsp;&nbsp;Output format is invisible = 0, visible = 1  
    **-c**  
    &nbsp;&nbsp;&nbsp;&nbsp;Consider the curvature of the earth  
    **-e**  
    &nbsp;&nbsp;&nbsp;&nbsp;Output format is invisible = NULL, else current elev - viewpoint_elev  
    **-r**  
    &nbsp;&nbsp;&nbsp;&nbsp;Consider atmospheric refraction  

=== "Python (grass.tools)"

    **input** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of input elevation raster map  
    **output** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Name for output raster map  
    **coordinates** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Coordinates of viewing position  
    **observer_elevation** : float, *optional*  
    &nbsp;&nbsp;&nbsp;&nbsp;Viewing elevation above the ground  

## DESCRIPTION

Computes the viewshed of a point on an elevation raster map.

Default format: NULL (invisible), vertical angle wrt viewpoint (visible).

## NOTES

Use the -b flag for binary visibility. Without it the output is elevation
differences for visible cells.

Only the integer raster input is supported.

## EXAMPLES

### Binary viewshed

```sh
r.viewshed input=elevation output=viewshed coordinates=635000,216500 -b
```
