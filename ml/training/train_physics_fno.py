"""Train the physics_fno model.  Usage: python -m ml.training.train_physics_fno [--dev] [--epochs N]"""

from ml.training.trainer import cli

if __name__ == "__main__":
    cli("physics_fno.yaml")
