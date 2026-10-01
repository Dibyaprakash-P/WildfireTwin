# Scenario definitions

Reference-simulation scenarios are generated programmatically by `ml/datasets/generate.py` from
`ml/configs/dataset.yaml` (ignitions, ERA5 start hours, live fuel moisture). Each scenario is stored in
`data/processed/training/<dataset_version>/scenarios/<id>.npz` with its metadata row in `scenarios.parquet`.
On-demand scenarios submitted through the API are stored in MongoDB (`simulations`) with their request body.
