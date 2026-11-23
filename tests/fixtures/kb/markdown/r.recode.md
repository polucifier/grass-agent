---
name: r.recode
description: Recodes categorical raster maps.
keywords: [ raster, recode categories, reclassification ]
---

# r.recode

Recodes categorical raster maps.

=== "Command line"

    **r.recode**
    [**-ad**]
    **input**=*name*
    **output**=*name*
    **rules**=*name*
    [**title**=*string*]
    [**--overwrite**]

    Example:

    ```sh
    r.recode input=name output=name rules=name
    ```

=== "Python (grass.tools)"

    *grass.tools.Tools.r_recode*(**input**,
        **output**,
        **rules**,
        **title**=*None*,
        **flags**=*None*,
        **overwrite**=*None*,
        **verbose**=*None*,
        **quiet**=*None*,
        **superquiet**=*None*)

    Example:

    ```python
    tools = Tools()
    tools.r_recode(input="name", output="name", rules="name")
    ```

## Parameters

=== "Command line"

    **input**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name of raster map to be recoded  
    **output**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;Name for output raster map  
    **rules**=*name* **[required]**  
    &nbsp;&nbsp;&nbsp;&nbsp;File containing recode rules  
    **-a**  
    &nbsp;&nbsp;&nbsp;&nbsp;Use the first category as the key  
    **-d**  
    &nbsp;&nbsp;&nbsp;&nbsp;Use the default category as the key  

## DESCRIPTION

Recodes categorical raster maps with a rules file.

## NOTES

Floating point input is supported through the rules file.

## EXAMPLES

### Recode categories

```sh
r.recode input=landcover output=landcover_recode rules=rules.txt
```
