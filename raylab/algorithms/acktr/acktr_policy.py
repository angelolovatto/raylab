"""ACKTR policy implemented in PyTorch."""
import collections

import numpy as np
import torch
import torch.nn as nn
from ray.rllib.evaluation.postprocessing import Postprocessing, compute_advantages
from ray.rllib.policy.policy import ACTION_LOGP
from ray.rllib.policy.sample_batch import SampleBatch
from ray.rllib.utils.annotations import override

from raylab.utils import hf_util
from raylab.utils.dictionaries import get_keys
from raylab.utils.explained_variance import explained_variance
from raylab.utils.kfac import KFACOptimizer
import raylab.utils.pytorch as ptu
from raylab.modules.distributions import Normal
from raylab.policy import TorchPolicy


class ACKTRTorchPolicy(TorchPolicy):
    """Policy class for Actor-Critic with Kronecker factored Trust Region."""

    # pylint:disable=abstract-method

    @staticmethod
    @override(TorchPolicy)
    def get_default_config():
        """Return the default configuration for ACKTR."""
        # pylint:disable=cyclic-import
        from raylab.algorithms.acktr.acktr import DEFAULT_CONFIG

        return DEFAULT_CONFIG

    @override(TorchPolicy)
    def optimizer(self):
        config = self.config["torch_optimizer"]
        components = ["actor", "critic"]

        actor_optim = KFACOptimizer(self.module.actor, **config["actor"])

        optim_type = config["critic"].pop("type")
        if optim_type == "KFAC":
            critic_optim = KFACOptimizer(self.module.critic, **config["critic"])
        else:
            critic_optim = ptu.get_optimizer_class(optim_type)(
                self.module.critic.parameters(), **config["critic"]
            )

        return collections.namedtuple("OptimizerCollection", components)(
            actor_optim, critic_optim
        )

    @override(TorchPolicy)
    def compute_module_ouput(self, input_dict, state=None, seq_lens=None):
        return input_dict[SampleBatch.CUR_OBS], state

    @torch.no_grad()
    @override(TorchPolicy)
    def postprocess_trajectory(
        self, sample_batch, other_agent_batches=None, episode=None
    ):
        sample_batch = super().postprocess_trajectory(
            sample_batch, other_agent_batches=other_agent_batches, episode=episode
        )

        last_obs = self.convert_to_tensor(sample_batch[SampleBatch.NEXT_OBS][-1])
        last_r = self.module.critic(last_obs).squeeze(-1).numpy()

        cur_obs = self.convert_to_tensor(sample_batch[SampleBatch.CUR_OBS])
        sample_batch[SampleBatch.VF_PREDS] = (
            self.module.critic(cur_obs).squeeze(-1).numpy()
        )
        sample_batch = compute_advantages(
            sample_batch,
            last_r,
            gamma=self.config["gamma"],
            lambda_=self.config["lambda"],
            use_gae=self.config["use_gae"],
        )
        return sample_batch

    @override(TorchPolicy)
    def learn_on_batch(self, samples):
        batch_tensors = self._lazy_tensor_dict(samples)
        info = {}

        info.update(self._update_actor(batch_tensors))
        info.update(self._update_critic(batch_tensors))
        info.update(self.extra_grad_info(batch_tensors))

        return self._learner_stats(info)

    def _update_actor(self, batch_tensors):
        info = {}
        cur_obs, actions, advantages = get_keys(
            batch_tensors,
            SampleBatch.CUR_OBS,
            SampleBatch.ACTIONS,
            Postprocessing.ADVANTAGES,
        )

        # Compute whitening matrices
        n_samples = self.config["logp_samples"]
        with self._optimizer.actor.record_stats():
            _, log_prob = self.module.actor.sample(cur_obs, (n_samples,))
            log_prob.mean().backward()

        # Compute surrogate loss
        self._optimizer.actor.zero_grad()
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        surr_loss = -(self.module.actor.log_prob(cur_obs, actions) * advantages).mean()
        info["loss(actor)"] = surr_loss.item()
        surr_loss.backward()
        pol_grad = [p.grad.clone() for p in self.module.actor.parameters()]
        self._optimizer.actor.step()

        if self.config["line_search"]:
            info.update(self._perform_line_search(pol_grad, surr_loss, batch_tensors))

        return info

    def _perform_line_search(self, pol_grad, surr_loss, batch_tensors):
        # pylint:disable=too-many-locals
        kl_clip = self._optimizer.actor.state["kl_clip"]
        expected_improvement = sum(
            (g * p.grad.data).sum()
            for g, p in zip(pol_grad, self.module.actor.parameters())
        ).item()

        cur_obs, actions, old_logp, advantages = get_keys(
            batch_tensors,
            SampleBatch.CUR_OBS,
            SampleBatch.ACTIONS,
            ACTION_LOGP,
            Postprocessing.ADVANTAGES,
        )

        @torch.no_grad()
        def f_barrier(scale):
            for par in self.module.actor.parameters():
                par.data.add_(scale, par.grad.data)
            new_logp = self.module.actor.log_prob(cur_obs, actions)
            for par in self.module.actor.parameters():
                par.data.sub_(scale, par.grad.data)
            surr_loss = self._compute_surr_loss(old_logp, new_logp, advantages)
            avg_kl = torch.mean(old_logp - new_logp)
            return surr_loss.item() if avg_kl < kl_clip else np.inf

        scale, expected_improvement, improvement = hf_util.line_search(
            f_barrier,
            1,
            1,
            expected_improvement,
            y_0=surr_loss.item(),
            **self.config["line_search_options"],
        )
        improvement_ratio = (
            improvement / expected_improvement if expected_improvement else np.nan
        )
        info = {
            "expected_improvement": expected_improvement,
            "actual_improvement": improvement,
            "improvement_ratio": improvement_ratio,
        }
        for par in self.module.actor.parameters():
            par.data.add_(scale, par.grad.data)
        return info

    @staticmethod
    def _compute_surr_loss(old_logp, new_logp, advantages):
        return -torch.mean(torch.exp(new_logp - old_logp) * advantages)

    def _update_critic(self, batch_tensors):
        cur_obs, value_targets = get_keys(
            batch_tensors, SampleBatch.CUR_OBS, Postprocessing.VALUE_TARGETS,
        )
        mse = nn.MSELoss()
        fake_dist = Normal()
        fake_scale = torch.ones_like(value_targets)

        for _ in range(self.config["vf_iters"]):
            if isinstance(self._optimizer.critic, KFACOptimizer):
                # Compute whitening matrices
                with self._optimizer.critic.record_stats():
                    values = self.module.critic(cur_obs).squeeze(-1)
                    fake_samples = values + torch.randn_like(values)
                    log_prob = fake_dist.log_prob(
                        fake_samples.detach(), {"loc": values, "scale": fake_scale}
                    )
                    log_prob.mean().backward()

            self._optimizer.critic.zero_grad()
            mse_loss = mse(self.module.critic(cur_obs).squeeze(-1), value_targets)
            mse_loss.backward()
            self._optimizer.critic.step()

        return {"loss(critic)": mse_loss.item()}

    @torch.no_grad()
    def extra_grad_info(self, batch_tensors):  # pylint:disable=unused-argument
        """Return statistics right after components are updated."""
        info = {}
        cur_obs, actions, old_logp, value_targets, value_preds = get_keys(
            batch_tensors,
            SampleBatch.CUR_OBS,
            SampleBatch.ACTIONS,
            ACTION_LOGP,
            Postprocessing.VALUE_TARGETS,
            SampleBatch.VF_PREDS,
        )

        info["kl_divergence"] = torch.mean(
            old_logp - self.module.actor.log_prob(cur_obs, actions)
        ).item()
        info["entropy"] = torch.mean(-old_logp).item()
        info["perplexity"] = torch.mean(-old_logp).exp().item()
        info["explained_variance"] = explained_variance(
            value_targets.numpy(), value_preds.numpy()
        )
        info.update(
            {
                f"grad_norm({k})": nn.utils.clip_grad_norm_(
                    self.module[k].parameters(), float("inf")
                )
                for k in ("actor", "critic")
            }
        )
        return info
