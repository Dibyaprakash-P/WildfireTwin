# FlamMap (offline, optional)

FlamMap's **Minimum Travel Time (MTT)** module produces an arrival-time raster that WildfireTwin can import
(`kind=arrival_raster`, `simulator=FlamMap`, `units` as exported). FlamMap is a Windows desktop application and is
deliberately **not** containerised or required by the web application.

The in-repo reference simulator (`simulation/rothermel.py`, `simulation/spread.py`) implements the same model family
(Rothermel surface spread + elliptical shape + minimum travel time) so that reference simulations can be produced
programmatically without FlamMap. Differences to FlamMap MTT: no crown fire, no spotting, no fuel-moisture
conditioning, spatially uniform weather in the window, simplified wind adjustment factors.

Full workflow (export → `python -m simulation.converters.import_cli` → `python -m simulation.converters.build_dataset`
→ separate engine-named dataset version): [`docs/farsite_flame_map_workflow.md`](../../docs/farsite_flame_map_workflow.md).
WTRS (the current training data) is produced by the internal Rothermel + MTT engine, not by this tool.
