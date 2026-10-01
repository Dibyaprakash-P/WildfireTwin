"""Train the unet model.  Usage: python -m ml.training.train_unet [--dev] [--epochs N]"""

from ml.training.trainer import cli

if __name__ == "__main__":
    cli("unet.yaml")
