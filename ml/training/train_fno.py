"""Train the fno model.  Usage: python -m ml.training.train_fno [--dev] [--epochs N]"""

from ml.training.trainer import cli

if __name__ == "__main__":
    cli("fno.yaml")
