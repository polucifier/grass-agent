---
name: r.reclass
description: Reclassify raster map based on category values.
keywords: [ raster, reclassification ]
---

# r.reclass

Reclassify raster map based on category values.

=== "Command line"

    **r.reclass**
    **input**=*name*
    **output**=*name*
    **rules**=*name*
    [**title**=*string*]
    [**--overwrite**]

    Example:

    ```sh
    r.reclass input=name output=name rules=name
    ```

=== "Python (grass.tools)"

    *grass.tools.Tools.r_reclass*(**input**,
        **output**,
        **rules**,
        **title**=*None*,
        **overwrite**=*None*,
        **verbose**=*None*,
        **quiet**=*None*,
        **superquiet**=*None*)

    Example:

    ```python
    tools = Tools()
    tools.r_reclass(input="name", output="name", rules="name")
    ```

=== "Python (grass.script)"

    *grass.script.run_command*("***r.reclass***",
        **input**,
        **output**,
        **rules**)

## Parameters

=== "Command line"

    **input**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of raster map to be reclassified  
    **output**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name for output raster map  
    **rules**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;File containing reclass rules  
    &nbsp;&nbsp;&nbsp;&nbsp;'-' for standard input  
    **title**=*string*  
    &nbsp;&nbsp;&nbsp;&nbsp;Title for output raster map  

=== "Python (grass.tools)"

    **input** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of raster map to be reclassified  
    **output** : str, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;Name for output raster map  
    **rules** : str | io.StringIO, *required*  
    &nbsp;&nbsp;&nbsp;&nbsp;File containing reclass rules  
    &nbsp;&nbsp;&nbsp;&nbsp;'-' for standard input  

## DESCRIPTION

Creates a new raster map whose category values are reclassified.

## NOTES

r.reclass only works on an integer input raster map; if the input map is
instead floating point data, you must multiply the input data by some factor to
achieve whole number input data.

Rules are a file or stream, not inline text passed as a plain string.

## EXAMPLES

### Reclassify slope

```sh
cat > rules.txt <<EOF
0 thru 15 = NULL
* = 1
EOF
r.reclass input=slope output=steep rules=rules.txt
```
