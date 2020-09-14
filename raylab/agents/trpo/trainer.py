"""Trainer and configuration for TRPO."""
from ray.rllib.utils import override

from raylab.agents.trainer import Trainer

from .policy import TRPOTorchPolicy


class TRPOTrainer(Trainer):
    """Single agent trainer for TRPO."""

    # pylint:disable=abstract-method
    _name = "TRPO"

    @staticmethod
    @override(Trainer)
    def validate_config(config: dict):
        assert not config[
            "learning_starts"
        ], "No point in having a warmup for an on-policy algorithm."

    @override(Trainer)
    def get_policy_class(self, _):
        return TRPOTorchPolicy
