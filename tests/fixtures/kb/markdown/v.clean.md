---
name: v.clean
description: Toolset for cleaning topology of vector map.
keywords: [ vector, topology, geometry, snapping ]
---

# v.clean

Toolset for cleaning topology of vector map.

=== "Command line"

    **v.clean**
    [**-bc**]
    **input**=*name*
    [**layer**=*string*]
    [**type**=*string* [,*string*,...]]
    **output**=*name*
    [**error**=*name*]
    **tool**=*string* [,*string*,...]
    [**threshold**=*float* [,*float*,...]]
    [**--overwrite**]

    Example:

    ```sh
    v.clean input=name output=name tool=break
    ```

=== "Python (grass.tools)"

    *grass.tools.Tools.v_clean*(**input**,
        **layer**=*"-1"*,
        **type**=*"point,line,boundary,centroid,area,face,kernel"*,
        **output**,
        **error**=*None*,
        **tool**,
        **threshold**=*None*,
        **flags**=*None*,
        **overwrite**=*None*,
        **verbose**=*None*,
        **quiet**=*None*,
        **superquiet**=*None*)

    Example:

    ```python
    tools = Tools()
    tools.v_clean(input="name", output="name", tool="break")
    ```

=== "Python (grass.script)"

    *grass.script.run_command*("***v.clean***",
        **input**,
        **output**)

## Parameters

=== "Command line"

    **input**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of input vector map  
    **layer**=*string*  
    &nbsp;&nbsp;&nbsp;&nbsp;Layer number or name ('-1' for all layers)  
    &nbsp;&nbsp;&nbsp;&nbsp;Default: *-1*  
    **type**=*string* [,*string*,...]  
    &nbsp;&nbsp;&nbsp;&nbsp;Input feature type  
    &nbsp;&nbsp;&nbsp;&nbsp;Allowed values: *point, line, boundary, centroid, area, face, kernel*  
    **output**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name for output vector map  
    **error**=*name*  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of output map where errors are written  
    **tool**=*string* [,*string*,...] **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Cleaning tool  
    &nbsp;&nbsp;&nbsp;&nbsp;Allowed values: *break, snap, rmdangle, chdangle, rmbridge, chbridge, rmdupl, rmdac, bpol, prune, rmarea, rmline, rmsa*  
    &nbsp;&nbsp;&nbsp;&nbsp;**rmdupl**: remove duplicate geometry features (pay attention to categories!)  
    &nbsp;&nbsp;&nbsp;&nbsp;**snap**: snap lines to vertex in threshold  
    **threshold**=*float* [,*float*,...]  
    &nbsp;&nbsp;&nbsp;&nbsp;One value for each tool; for threshold units, see each tool  
    &nbsp;&nbsp;&nbsp;&nbsp;Default: 0.0[,0.0,...])  
    **-b**  
    &nbsp;&nbsp;&nbsp;&nbsp;Do not build topology for the output vector  
    **-c**  
    &nbsp;&nbsp;&nbsp;&nbsp;Combine tools with recommended follow-up tools  

=== "Python (grass.tools)"

    **input** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of input vector map  
    **output** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Name for output vector map  
    **tool** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Cleaning tool  
    **threshold** : float, *optional*  
    &nbsp;&nbsp;&nbsp;&nbsp;One value for each tool  

## DESCRIPTION

The v.clean module cleans vector topology.

## NOTES

The user does not have to run v.build on the output vector unless the -b flag
was used. The rmdupl tool removes duplicate geometry features. Use rmdupl after
breaking lines.

## EXAMPLES

### Remove duplicates

```sh
v.clean input=roads output=roads_clean tool=rmdupl
```
