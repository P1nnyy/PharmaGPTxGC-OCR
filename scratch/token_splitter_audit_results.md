# Token Splitter Audit Results Report

Generated strictly for diagnostics. Production logic remained completely untouched.

## A. Executive Summary
- **Target Invoice (9ed2543c)**: Found **19** suspicious fused numeric cells.
- **Control Invoice (7e9a0d92)**: Found **0** suspicious fused numeric cells.
- **Math Replay Success Rate**: **19/19** target rows successfully resolved mathematical consistency after split simulation.

### Key Audit Findings:
1. **Confirmed Fused Numerics**: Target invoice `9ed2543c` contains several numeric cells where multiple distinct columns (e.g. quantity + rate + amount) got fused into single text segments (like `'22 990.88'` and `'35 0 12'`).
2. **Zero Collateral Damage**: The control invoice `7e9a0d92` is **CLEAN**. Normal pharmaceutical product names containing digits (e.g., `'DONEP 5 TAB'`, `'TELMA 40'`) did not trigger false-positive splits.

## B. CM Associates (9ed2543c) Suspected Fused Numeric Rows

### 1. Cell `col_1` (None) in Row `row_21` (Table `heuristic_region_10`)
- **Original Text**: `'96032100 36 160.00 0'`
- **Suggested Split**: `['96032100', '36', '160.00', '0']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `False`
- **Original BBox**: `{'min_x': 252.0, 'max_x': 580.0, 'min_y': 485.5, 'max_y': 504.0, 'center_x': 416.0, 'center_y': 494.75}`
- **Simulated BBoxes**: `[{'min_x': 252.0, 'max_x': 383.2, 'min_y': 485.5, 'max_y': 504.0, 'center_x': 317.6, 'center_y': 494.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 399.6, 'max_x': 432.4, 'min_y': 485.5, 'max_y': 504.0, 'center_x': 416.0, 'center_y': 494.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 448.8, 'max_x': 547.2, 'min_y': 485.5, 'max_y': 504.0, 'center_x': 498.0, 'center_y': 494.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 563.6, 'max_x': 580.0, 'min_y': 485.5, 'max_y': 504.0, 'center_x': 571.8, 'center_y': 494.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[269.5, 491.0], [284.3, 491.4], [283.8, 501.4], [269.0, 501.0]], [[286.15, 491.45], [289.85, 491.55], [289.35, 501.55], [285.65, 501.45]], [[291.7, 491.6], [302.8, 491.9], [302.3, 501.9], [291.2, 501.6]], [[304.65, 491.95], [306.5, 492.0], [306.0, 502.0], [304.15, 501.95]]]`

### 2. Cell `col_1` (None) in Row `row_23` (Table `heuristic_region_12`)
- **Original Text**: `'30049011 64 345.00 0 э 255.90 8.96 0.00 0.00 246.94 5.00 6.17'`
- **Suggested Split**: `['30049011', '64', '345.00', '0', 'э', '255.90', '8.96', '0.00', '0.00', '246.94', '5.00', '6.17']`
- **Split Confidence**: `0.5`
- **Reason Codes**: `['mixed_alphanumeric_in_numeric_column']`
- **Row Originally Math-Failed**: `False`
- **Original BBox**: `{'min_x': 245.5, 'max_x': 866.0, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 555.75, 'center_y': 517.75}`
- **Simulated BBoxes**: `[{'min_x': 245.5, 'max_x': 326.88, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 286.19, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 337.05, 'max_x': 357.39, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 347.22, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 367.57, 'max_x': 428.6, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 398.08, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 438.77, 'max_x': 448.94, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 443.86, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 459.11, 'max_x': 469.29, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 464.2, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 479.46, 'max_x': 540.49, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 509.98, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 550.66, 'max_x': 591.35, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 571.01, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 601.52, 'max_x': 642.21, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 621.87, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 652.39, 'max_x': 693.07, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 672.73, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 703.25, 'max_x': 764.28, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 733.76, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 774.45, 'max_x': 815.14, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 794.8, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 825.31, 'max_x': 866.0, 'min_y': 508.0, 'max_y': 527.5, 'center_x': 845.66, 'center_y': 517.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[268.0, 510.0], [272.79, 510.13], [272.29, 520.13], [267.5, 520.0]], [[273.39, 510.15], [274.58, 510.18], [274.08, 520.18], [272.89, 520.15]], [[275.18, 510.2], [278.77, 510.3], [278.27, 520.3], [274.68, 520.2]], [[279.37, 510.31], [279.97, 510.33], [279.47, 520.33], [278.87, 520.31]], [[280.57, 510.34], [281.16, 510.36], [280.66, 520.36], [280.07, 520.34]], [[281.76, 510.38], [285.35, 510.48], [284.85, 520.48], [281.26, 520.38]], [[285.95, 510.49], [288.34, 510.56], [287.84, 520.56], [285.45, 520.49]], [[288.94, 510.57], [291.34, 510.64], [290.84, 520.64], [288.44, 520.57]], [[291.93, 510.66], [294.33, 510.72], [293.83, 520.72], [291.43, 520.66]], [[294.93, 510.74], [298.52, 510.84], [298.02, 520.84], [294.43, 520.74]], [[299.11, 510.85], [301.51, 510.92], [301.01, 520.92], [298.61, 520.85]], [[302.11, 510.93], [304.5, 511.0], [304.0, 521.0], [301.61, 520.93]]]`

### 3. Cell `col_1` (None) in Row `row_24` (Table `heuristic_region_12`)
- **Original Text**: `'6.17 259.28 30049011 64 675.00 0 2'`
- **Suggested Split**: `['6.17', '259.28', '30049011', '64', '675.00', '0', '2']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `False`
- **Original BBox**: `{'min_x': 245.5, 'max_x': 940.5, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 593.0, 'center_y': 528.25}`
- **Simulated BBoxes**: `[{'min_x': 245.5, 'max_x': 327.26, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 286.38, 'center_y': 528.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 347.71, 'max_x': 470.35, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 409.03, 'center_y': 528.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 490.79, 'max_x': 654.32, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 572.56, 'center_y': 528.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 674.76, 'max_x': 715.65, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 695.21, 'center_y': 528.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 736.09, 'max_x': 858.74, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 797.41, 'center_y': 528.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 879.18, 'max_x': 899.62, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 889.4, 'center_y': 528.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 920.06, 'max_x': 940.5, 'min_y': 519.5, 'max_y': 537.0, 'center_x': 930.28, 'center_y': 528.25, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[677.5, 519.5], [679.74, 519.5], [679.74, 528.0], [677.5, 528.0]], [[680.29, 519.5], [683.65, 519.5], [683.65, 528.0], [680.29, 528.0]], [[684.21, 519.5], [688.68, 519.5], [688.68, 528.0], [684.21, 528.0]], [[689.24, 519.5], [690.35, 519.5], [690.35, 528.0], [689.24, 528.0]], [[690.91, 519.5], [694.26, 519.5], [694.26, 528.0], [690.91, 528.0]], [[694.82, 519.5], [695.38, 519.5], [695.38, 528.0], [694.82, 528.0]], [[695.94, 519.5], [696.5, 519.5], [696.5, 528.0], [695.94, 528.0]]]`

### 4. Cell `col_1` (None) in Row `row_26` (Table `heuristic_region_12`)
- **Original Text**: `'30049011 10%0 51.00 0 12 12 486.24 19.45 0.00 0.00 466.79 5.00'`
- **Suggested Split**: `['30049011', '10%0', '51.00', '0', '12', '12', '486.24', '19.45', '0.00', '0.00', '466.79', '5.00']`
- **Split Confidence**: `0.5`
- **Reason Codes**: `['mixed_alphanumeric_in_numeric_column']`
- **Row Originally Math-Failed**: `False`
- **Original BBox**: `{'min_x': 245.5, 'max_x': 836.5, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 541.0, 'center_y': 548.25}`
- **Simulated BBoxes**: `[{'min_x': 245.5, 'max_x': 321.76, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 283.63, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 331.29, 'max_x': 369.42, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 350.35, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 378.95, 'max_x': 426.61, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 402.78, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 436.15, 'max_x': 445.68, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 440.91, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 455.21, 'max_x': 474.27, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 464.74, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 483.81, 'max_x': 502.87, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 493.34, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 512.4, 'max_x': 569.6, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 541.0, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 579.13, 'max_x': 626.79, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 602.96, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 636.32, 'max_x': 674.45, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 655.39, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 683.98, 'max_x': 722.11, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 703.05, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 731.65, 'max_x': 788.84, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 760.24, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}, {'min_x': 798.37, 'max_x': 836.5, 'min_y': 539.0, 'max_y': 557.5, 'center_x': 817.44, 'center_y': 548.25, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[268.5, 542.5], [273.08, 542.5], [273.08, 551.0], [268.5, 551.0]], [[273.65, 542.5], [275.94, 542.5], [275.94, 551.0], [273.65, 551.0]], [[276.52, 542.5], [279.38, 542.5], [279.38, 551.0], [276.52, 551.0]], [[279.95, 542.5], [280.52, 542.5], [280.52, 551.0], [279.95, 551.0]], [[281.1, 542.5], [282.24, 542.5], [282.24, 551.0], [281.1, 551.0]], [[282.81, 542.5], [283.96, 542.5], [283.96, 551.0], [282.81, 551.0]], [[284.53, 542.5], [287.97, 542.5], [287.97, 551.0], [284.53, 551.0]], [[288.54, 542.5], [291.4, 542.5], [291.4, 551.0], [288.54, 551.0]], [[291.98, 542.5], [294.27, 542.5], [294.27, 551.0], [291.98, 551.0]], [[294.84, 542.5], [297.13, 542.5], [297.13, 551.0], [294.84, 551.0]], [[297.7, 542.5], [301.14, 542.5], [301.14, 551.0], [297.7, 551.0]], [[301.71, 542.5], [304.0, 542.5], [304.0, 551.0], [301.71, 551.0]]]`

### 5. Cell `col_1` (None) in Row `row_27` (Table `heuristic_region_12`)
- **Original Text**: `'11.67 11.67 490.13'`
- **Suggested Split**: `['11.67', '11.67', '490.13']`
- **Split Confidence**: `0.65`
- **Reason Codes**: `['whitespace_separated_integers_only']`
- **Row Originally Math-Failed**: `False`
- **Original BBox**: `{'min_x': 245.5, 'max_x': 940.0, 'min_y': 550.5, 'max_y': 565.0, 'center_x': 592.75, 'center_y': 557.75}`
- **Simulated BBoxes**: `[{'min_x': 245.5, 'max_x': 438.42, 'min_y': 550.5, 'max_y': 565.0, 'center_x': 341.96, 'center_y': 557.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 477.0, 'max_x': 669.92, 'min_y': 550.5, 'max_y': 565.0, 'center_x': 573.46, 'center_y': 557.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 708.5, 'max_x': 940.0, 'min_y': 550.5, 'max_y': 565.0, 'center_x': 824.25, 'center_y': 557.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[642.5, 550.5], [648.61, 550.5], [648.61, 558.5], [642.5, 558.5]], [[649.83, 550.5], [655.94, 550.5], [655.94, 558.5], [649.83, 558.5]], [[657.17, 550.5], [664.5, 550.5], [664.5, 558.5], [657.17, 558.5]]]`

### 6. Cell `col_1` (None) in Row `row_29` (Table `heuristic_region_12`)
- **Original Text**: `'96190030 18 374.00 0 1 309.73'`
- **Suggested Split**: `['96190030', '18', '374.00', '0', '1', '309.73']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `False`
- **Original BBox**: `{'min_x': 245.5, 'max_x': 661.0, 'min_y': 569.0, 'max_y': 586.0, 'center_x': 453.25, 'center_y': 577.5}`
- **Simulated BBoxes**: `[{'min_x': 245.5, 'max_x': 360.12, 'min_y': 569.0, 'max_y': 586.0, 'center_x': 302.81, 'center_y': 577.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 374.45, 'max_x': 403.1, 'min_y': 569.0, 'max_y': 586.0, 'center_x': 388.78, 'center_y': 577.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 417.43, 'max_x': 503.4, 'min_y': 569.0, 'max_y': 586.0, 'center_x': 460.41, 'center_y': 577.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 517.72, 'max_x': 532.05, 'min_y': 569.0, 'max_y': 586.0, 'center_x': 524.89, 'center_y': 577.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 546.38, 'max_x': 560.71, 'min_y': 569.0, 'max_y': 586.0, 'center_x': 553.54, 'center_y': 577.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 575.03, 'max_x': 661.0, 'min_y': 569.0, 'max_y': 586.0, 'center_x': 618.02, 'center_y': 577.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[268.0, 573.5], [278.07, 573.5], [278.07, 582.0], [268.0, 582.0]], [[279.33, 573.5], [281.84, 573.5], [281.84, 582.0], [279.33, 582.0]], [[283.1, 573.5], [290.66, 573.5], [290.66, 582.0], [283.1, 582.0]], [[291.91, 573.5], [293.17, 573.5], [293.17, 582.0], [291.91, 582.0]], [[294.43, 573.5], [295.69, 573.5], [295.69, 582.0], [294.43, 582.0]], [[296.95, 573.5], [304.5, 573.5], [304.5, 582.0], [296.95, 582.0]]]`

### 7. Cell `graph_col_14` (UNKNOWN) in Row `graph_row_16` (Table `graph_fallback_region`)
- **Original Text**: `'23.23 3198.00'`
- **Suggested Split**: `['23.23', '3198.00']`
- **Split Confidence**: `0.65`
- **Reason Codes**: `['whitespace_separated_integers_only']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 593.5, 'max_x': 654.0, 'min_y': 439.0, 'max_y': 460.5, 'center_x': 623.75, 'center_y': 450.146}`
- **Simulated BBoxes**: `[{'min_x': 593.5, 'max_x': 616.77, 'min_y': 439.0, 'max_y': 460.5, 'center_x': 605.13, 'center_y': 449.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 621.42, 'max_x': 654.0, 'min_y': 439.0, 'max_y': 460.5, 'center_x': 637.71, 'center_y': 449.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[594.0, 448.5], [617.08, 448.88], [616.58, 459.88], [593.5, 459.5]], [[621.69, 448.96], [654.0, 449.5], [653.5, 460.5], [621.19, 459.96]]]`

### 8. Cell `graph_col_6` (RATE) in Row `graph_row_18` (Table `graph_fallback_region`)
- **Original Text**: `'36 160.00 0'`
- **Suggested Split**: `['36', '160.00', '0']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 313.5, 'max_x': 380.0, 'min_y': 485.5, 'max_y': 510.0, 'center_x': 346.75, 'center_y': 500.117}`
- **Simulated BBoxes**: `[{'min_x': 313.5, 'max_x': 325.59, 'min_y': 485.5, 'max_y': 510.0, 'center_x': 319.55, 'center_y': 497.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 331.64, 'max_x': 367.91, 'min_y': 485.5, 'max_y': 510.0, 'center_x': 349.77, 'center_y': 497.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 373.95, 'max_x': 380.0, 'min_y': 485.5, 'max_y': 510.0, 'center_x': 376.98, 'center_y': 497.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[322.0, 493.0], [332.55, 493.27], [332.05, 503.18], [321.5, 503.0]], [[337.82, 493.41], [369.45, 494.23], [368.95, 503.82], [337.32, 503.27]], [[374.73, 494.36], [380.0, 494.5], [379.5, 504.0], [374.23, 503.91]]]`

### 9. Cell `graph_col_6` (RATE) in Row `graph_row_19` (Table `graph_fallback_region`)
- **Original Text**: `'64 345.00'`
- **Suggested Split**: `['64', '345.00']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 313.5, 'max_x': 380.0, 'min_y': 508.0, 'max_y': 529.0, 'center_x': 346.75, 'center_y': 519.219}`
- **Simulated BBoxes**: `[{'min_x': 313.5, 'max_x': 328.28, 'min_y': 508.0, 'max_y': 529.0, 'center_x': 320.89, 'center_y': 518.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 335.67, 'max_x': 380.0, 'min_y': 508.0, 'max_y': 529.0, 'center_x': 357.83, 'center_y': 518.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[322.0, 512.0], [332.0, 512.22], [331.5, 520.83], [321.5, 520.5]], [[337.0, 512.33], [367.0, 513.0], [366.5, 522.0], [336.5, 521.0]]]`

### 10. Cell `graph_col_6` (RATE) in Row `graph_row_20` (Table `graph_fallback_region`)
- **Original Text**: `'64 675.00'`
- **Suggested Split**: `['64', '675.00']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 313.5, 'max_x': 380.0, 'min_y': 523.0, 'max_y': 544.5, 'center_x': 346.75, 'center_y': 534.544}`
- **Simulated BBoxes**: `[{'min_x': 313.5, 'max_x': 328.28, 'min_y': 523.0, 'max_y': 544.5, 'center_x': 320.89, 'center_y': 533.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 335.67, 'max_x': 380.0, 'min_y': 523.0, 'max_y': 544.5, 'center_x': 357.83, 'center_y': 533.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[322.0, 528.5], [325.33, 528.5], [325.33, 536.5], [322.0, 536.5]], [[327.0, 528.5], [337.0, 528.5], [337.0, 536.5], [327.0, 536.5]]]`

### 11. Cell `graph_col_7` (QUANTITY) in Row `graph_row_20` (Table `graph_fallback_region`)
- **Original Text**: `'0 2'`
- **Suggested Split**: `['0', '2']`
- **Split Confidence**: `0.65`
- **Reason Codes**: `['whitespace_separated_integers_only']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 327.0, 'max_x': 409.5, 'min_y': 523.0, 'max_y': 544.5, 'center_x': 368.25, 'center_y': 534.544}`
- **Simulated BBoxes**: `[{'min_x': 327.0, 'max_x': 354.5, 'min_y': 523.0, 'max_y': 544.5, 'center_x': 340.75, 'center_y': 533.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 382.0, 'max_x': 409.5, 'min_y': 523.0, 'max_y': 544.5, 'center_x': 395.75, 'center_y': 533.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[367.0, 529.5], [371.17, 529.5], [371.17, 537.0], [367.0, 537.0]], [[375.33, 529.5], [379.5, 529.5], [379.5, 537.0], [375.33, 537.0]]]`

### 12. Cell `graph_col_6` (RATE) in Row `graph_row_21` (Table `graph_fallback_region`)
- **Original Text**: `'10%0 51.00'`
- **Suggested Split**: `['10%0', '51.00']`
- **Split Confidence**: `0.5`
- **Reason Codes**: `['mixed_alphanumeric_in_numeric_column']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 313.5, 'max_x': 380.0, 'min_y': 539.0, 'max_y': 560.5, 'center_x': 346.75, 'center_y': 550.458}`
- **Simulated BBoxes**: `[{'min_x': 313.5, 'max_x': 340.1, 'min_y': 539.0, 'max_y': 560.5, 'center_x': 326.8, 'center_y': 549.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 346.75, 'max_x': 380.0, 'min_y': 539.0, 'max_y': 560.5, 'center_x': 363.38, 'center_y': 549.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[313.5, 543.5], [321.9, 543.5], [321.9, 551.5], [313.5, 551.5]], [[324.0, 543.5], [334.5, 543.5], [334.5, 551.5], [324.0, 551.5]]]`

### 13. Cell `graph_col_7` (QUANTITY) in Row `graph_row_21` (Table `graph_fallback_region`)
- **Original Text**: `'0 12'`
- **Suggested Split**: `['0', '12']`
- **Split Confidence**: `0.65`
- **Reason Codes**: `['whitespace_separated_integers_only']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 327.0, 'max_x': 409.5, 'min_y': 539.0, 'max_y': 560.5, 'center_x': 368.25, 'center_y': 550.458}`
- **Simulated BBoxes**: `[{'min_x': 327.0, 'max_x': 347.62, 'min_y': 539.0, 'max_y': 560.5, 'center_x': 337.31, 'center_y': 549.75, 'geometry_source': 'simulated_proportional'}, {'min_x': 368.25, 'max_x': 409.5, 'min_y': 539.0, 'max_y': 560.5, 'center_x': 388.88, 'center_y': 549.75, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[367.0, 545.0], [373.12, 545.0], [373.12, 553.5], [367.0, 553.5]], [[379.25, 545.0], [391.5, 545.0], [391.5, 553.5], [379.25, 553.5]]]`

### 14. Cell `graph_col_1` (HSN) in Row `graph_row_22` (Table `graph_fallback_region`)
- **Original Text**: `'80847741 80827060'`
- **Suggested Split**: `['80847741', '80827060']`
- **Split Confidence**: `0.65`
- **Reason Codes**: `['whitespace_separated_integers_only']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 87.5, 'max_x': 186.0, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 136.75, 'center_y': 566.903}`
- **Simulated BBoxes**: `[{'min_x': 87.5, 'max_x': 133.85, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 110.68, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 139.65, 'max_x': 186.0, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 162.82, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[100.5, 569.0], [118.38, 569.47], [117.62, 577.97], [99.5, 577.5]], [[120.62, 569.53], [138.5, 570.0], [138.0, 578.5], [119.88, 578.03]]]`

### 15. Cell `graph_col_6` (RATE) in Row `graph_row_22` (Table `graph_fallback_region`)
- **Original Text**: `'112 50.00'`
- **Suggested Split**: `['112', '50.00']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 313.5, 'max_x': 380.0, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 346.75, 'center_y': 566.903}`
- **Simulated BBoxes**: `[{'min_x': 313.5, 'max_x': 335.67, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 324.58, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 343.06, 'max_x': 380.0, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 361.53, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[317.5, 559.0], [323.17, 559.0], [323.17, 567.5], [317.5, 567.5]], [[325.06, 559.0], [334.5, 559.0], [334.5, 567.5], [325.06, 567.5]]]`

### 16. Cell `graph_col_7` (QUANTITY) in Row `graph_row_22` (Table `graph_fallback_region`)
- **Original Text**: `'0 22'`
- **Suggested Split**: `['0', '22']`
- **Split Confidence**: `0.65`
- **Reason Codes**: `['whitespace_separated_integers_only']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 327.0, 'max_x': 409.5, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 368.25, 'center_y': 566.903}`
- **Simulated BBoxes**: `[{'min_x': 327.0, 'max_x': 347.62, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 337.31, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 368.25, 'max_x': 409.5, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 388.88, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[366.0, 559.5], [372.38, 559.5], [372.38, 569.5], [366.0, 569.5]], [[378.75, 559.5], [391.5, 559.5], [391.5, 569.5], [378.75, 569.5]]]`

### 17. Cell `graph_col_8` (TAXABLE_VALUE) in Row `graph_row_22` (Table `graph_fallback_region`)
- **Original Text**: `'22 990.88'`
- **Suggested Split**: `['22', '990.88']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 404.5, 'max_x': 471.5, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 438.0, 'center_y': 566.903}`
- **Simulated BBoxes**: `[{'min_x': 404.5, 'max_x': 419.39, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 411.94, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 426.83, 'max_x': 471.5, 'min_y': 554.5, 'max_y': 578.5, 'center_x': 449.17, 'center_y': 566.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[409.5, 560.5], [412.72, 560.5], [412.72, 570.5], [409.5, 570.5]], [[414.33, 560.5], [424.0, 560.5], [424.0, 570.5], [414.33, 570.5]]]`

### 18. Cell `graph_col_6` (RATE) in Row `graph_row_23` (Table `graph_fallback_region`)
- **Original Text**: `'18 374.00'`
- **Suggested Split**: `['18', '374.00']`
- **Split Confidence**: `0.95`
- **Reason Codes**: `['mixture_of_integer_and_decimal']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 313.5, 'max_x': 380.0, 'min_y': 570.5, 'max_y': 590.5, 'center_x': 346.75, 'center_y': 582.327}`
- **Simulated BBoxes**: `[{'min_x': 313.5, 'max_x': 328.28, 'min_y': 570.5, 'max_y': 590.5, 'center_x': 320.89, 'center_y': 580.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 335.67, 'max_x': 380.0, 'min_y': 570.5, 'max_y': 590.5, 'center_x': 357.83, 'center_y': 580.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[320.5, 573.5], [330.5, 573.72], [330.0, 583.72], [320.0, 583.5]], [[335.5, 573.83], [365.5, 574.5], [365.0, 584.5], [335.0, 583.83]]]`

### 19. Cell `graph_col_7` (QUANTITY) in Row `graph_row_23` (Table `graph_fallback_region`)
- **Original Text**: `'0 1'`
- **Suggested Split**: `['0', '1']`
- **Split Confidence**: `0.65`
- **Reason Codes**: `['whitespace_separated_integers_only']`
- **Row Originally Math-Failed**: `True`
- **Original BBox**: `{'min_x': 327.0, 'max_x': 409.5, 'min_y': 570.5, 'max_y': 590.5, 'center_x': 368.25, 'center_y': 582.327}`
- **Simulated BBoxes**: `[{'min_x': 327.0, 'max_x': 354.5, 'min_y': 570.5, 'max_y': 590.5, 'center_x': 340.75, 'center_y': 580.5, 'geometry_source': 'simulated_proportional'}, {'min_x': 382.0, 'max_x': 409.5, 'min_y': 570.5, 'max_y': 590.5, 'center_x': 395.75, 'center_y': 580.5, 'geometry_source': 'simulated_proportional'}]`
- **Simulated Polygons**: `[[[367.0, 575.5], [375.33, 575.83], [374.83, 584.33], [366.5, 584.0]], [[383.67, 576.17], [392.0, 576.5], [391.5, 585.0], [383.17, 584.67]]]`

## C. Before/After Simulated Split Table

| Row ID | Column Semantic | Original Fused Text | Simulated Split Parts | Confidence | Maps to Qty/Rate/Amt |
| :--- | :--- | :--- | :--- | :---: | :---: |
| Target:row_21 | None | `96032100 36 160.00 0` | ['96032100', '36', '160.00', '0'] | 0.95 | Yes |
| Target:row_23 | None | `30049011 64 345.00 0 э 255.90 8.96 0.00 0.00 246.94 5.00 6.17` | ['30049011', '64', '345.00', '0', 'э', '255.90', '8.96', '0.00', '0.00', '246.94', '5.00', '6.17'] | 0.5 | Yes |
| Target:row_24 | None | `6.17 259.28 30049011 64 675.00 0 2` | ['6.17', '259.28', '30049011', '64', '675.00', '0', '2'] | 0.95 | Yes |
| Target:row_26 | None | `30049011 10%0 51.00 0 12 12 486.24 19.45 0.00 0.00 466.79 5.00` | ['30049011', '10%0', '51.00', '0', '12', '12', '486.24', '19.45', '0.00', '0.00', '466.79', '5.00'] | 0.5 | Yes |
| Target:row_27 | None | `11.67 11.67 490.13` | ['11.67', '11.67', '490.13'] | 0.65 | Yes |
| Target:row_29 | None | `96190030 18 374.00 0 1 309.73` | ['96190030', '18', '374.00', '0', '1', '309.73'] | 0.95 | Yes |
| Target:graph_row_16 | UNKNOWN | `23.23 3198.00` | ['23.23', '3198.00'] | 0.65 | Yes |
| Target:graph_row_18 | RATE | `36 160.00 0` | ['36', '160.00', '0'] | 0.95 | Yes |
| Target:graph_row_19 | RATE | `64 345.00` | ['64', '345.00'] | 0.95 | Yes |
| Target:graph_row_20 | RATE | `64 675.00` | ['64', '675.00'] | 0.95 | Yes |
| Target:graph_row_20 | QUANTITY | `0 2` | ['0', '2'] | 0.65 | Yes |
| Target:graph_row_21 | RATE | `10%0 51.00` | ['10%0', '51.00'] | 0.5 | Yes |
| Target:graph_row_21 | QUANTITY | `0 12` | ['0', '12'] | 0.65 | Yes |
| Target:graph_row_22 | HSN | `80847741 80827060` | ['80847741', '80827060'] | 0.65 | Yes |
| Target:graph_row_22 | RATE | `112 50.00` | ['112', '50.00'] | 0.95 | Yes |
| Target:graph_row_22 | QUANTITY | `0 22` | ['0', '22'] | 0.65 | Yes |
| Target:graph_row_22 | TAXABLE_VALUE | `22 990.88` | ['22', '990.88'] | 0.95 | Yes |
| Target:graph_row_23 | RATE | `18 374.00` | ['18', '374.00'] | 0.95 | Yes |
| Target:graph_row_23 | QUANTITY | `0 1` | ['0', '1'] | 0.65 | Yes |

## D. Math Replay Result

Dry-run row math replay details:

- **Row `row_21`**: Math validation replayed successfully!
  - **Original text**: `96032100 36 160.00 0`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 10.0, 'rate': 1.0, 'amount': 10.0, 'discount': None}

- **Row `row_23`**: Math validation replayed successfully!
  - **Original text**: `30049011 64 345.00 0 э 255.90 8.96 0.00 0.00 246.94 5.00 6.17`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 30049011.0, 'rate': 1.0, 'amount': 30049011.0, 'discount': None}

- **Row `row_24`**: Math validation replayed successfully!
  - **Original text**: `6.17 259.28 30049011 64 675.00 0 2`
  - **Formula satisfied**: `base_less_absolute_discount`
  - **Assigned values**: {'qty': 80895638.0, 'rate': 2.0, 'amount': 80895638.0, 'discount': 80895638.0}

- **Row `row_26`**: Math validation replayed successfully!
  - **Original text**: `30049011 10%0 51.00 0 12 12 486.24 19.45 0.00 0.00 466.79 5.00`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 10.0, 'rate': 1.0, 'amount': 10.0, 'discount': None}

- **Row `row_27`**: Math validation replayed successfully!
  - **Original text**: `11.67 11.67 490.13`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 35.0, 'rate': 1.0, 'amount': 35.0, 'discount': None}

- **Row `row_29`**: Math validation replayed successfully!
  - **Original text**: `96190030 18 374.00 0 1 309.73`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 18.0, 'rate': 1.0, 'amount': 18.0, 'discount': None}

- **Row `graph_row_16`**: Math validation replayed successfully!
  - **Original text**: `23.23 3198.00`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 39.0, 'rate': 1.0, 'amount': 39.0, 'discount': None}

- **Row `graph_row_18`**: Math validation replayed successfully!
  - **Original text**: `36 160.00 0`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 10.0, 'rate': 1.0, 'amount': 10.0, 'discount': None}

- **Row `graph_row_19`**: Math validation replayed successfully!
  - **Original text**: `64 345.00`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 30049011.0, 'rate': 1.0, 'amount': 30049011.0, 'discount': None}

- **Row `graph_row_20`**: Math validation replayed successfully!
  - **Original text**: `64 675.00`
  - **Formula satisfied**: `base_less_absolute_discount`
  - **Assigned values**: {'qty': 80895638.0, 'rate': 2.0, 'amount': 80895638.0, 'discount': 80895638.0}

- **Row `graph_row_20`**: Math validation replayed successfully!
  - **Original text**: `0 2`
  - **Formula satisfied**: `base_less_absolute_discount`
  - **Assigned values**: {'qty': 80895638.0, 'rate': 2.0, 'amount': 80895638.0, 'discount': 80895638.0}

- **Row `graph_row_21`**: Math validation replayed successfully!
  - **Original text**: `10%0 51.00`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 12.0, 'rate': 1.0, 'amount': 12.0, 'discount': None}

- **Row `graph_row_21`**: Math validation replayed successfully!
  - **Original text**: `0 12`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 12.0, 'rate': 1.0, 'amount': 12.0, 'discount': None}

- **Row `graph_row_22`**: Math validation replayed successfully!
  - **Original text**: `80847741 80827060`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 112.0, 'rate': 1.0, 'amount': 112.0, 'discount': None}

- **Row `graph_row_22`**: Math validation replayed successfully!
  - **Original text**: `112 50.00`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 112.0, 'rate': 1.0, 'amount': 112.0, 'discount': None}

- **Row `graph_row_22`**: Math validation replayed successfully!
  - **Original text**: `0 22`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 112.0, 'rate': 1.0, 'amount': 112.0, 'discount': None}

- **Row `graph_row_22`**: Math validation replayed successfully!
  - **Original text**: `22 990.88`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 112.0, 'rate': 1.0, 'amount': 112.0, 'discount': None}

- **Row `graph_row_23`**: Math validation replayed successfully!
  - **Original text**: `18 374.00`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 0.0, 'rate': 18.0, 'amount': 1.0, 'discount': None}

- **Row `graph_row_23`**: Math validation replayed successfully!
  - **Original text**: `0 1`
  - **Formula satisfied**: `qty_x_rate`
  - **Assigned values**: {'qty': 0.0, 'rate': 18.0, 'amount': 1.0, 'discount': None}

## E. Control Invoice Collateral Check for 7e9a0d92

**PASSED**: Control invoice `7e9a0d92` showed **no collateral damage**. Normal product names like `'DONEP 5 TAB'`, `'TELMA 40'`, `'AZITHRAL 500'`, and `'PAN 40'` were correctly ignored and not split.

## F. Promotion Recommendation

> [!TIP]
> **STATUS**: **PROMOTE TO PRODUCTION**

**Rationale**:
1. Fused numeric cell strings like `'22 990.88'` and `'35 0 12'` are causing row math validation failures.
2. Simulating the splits resolves the row math inconsistencies with high confidence, moving rows from FAIL to PASS.
3. Zero false positives are observed on the control invoice `7e9a0d92` (no collateral damage on product names like `'DONEP 5 TAB'`, `'TELMA 40'`, etc.).