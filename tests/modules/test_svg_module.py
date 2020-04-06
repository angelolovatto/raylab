# pylint: disable=missing-docstring,redefined-outer-name,protected-access
from functools import partial

import pytest
import torch
from ray.rllib.policy.sample_batch import SampleBatch

from raylab.modules.svg_module import SVGModule


@pytest.fixture(params=("svg_paper", "default"), ids=("SVG Encoder", "Default Encoder"))
def model_encoder(request):
    return request.param


@pytest.fixture
def module_batch_fn(module_and_batch_fn):
    return partial(module_and_batch_fn, SVGModule)


def test_model_params(module_batch_fn, model_encoder):
    module, batch = module_batch_fn({"model": {"encoder": model_encoder}})

    params = module.model(batch[SampleBatch.CUR_OBS], batch[SampleBatch.ACTIONS])
    assert "loc" in params
    assert "scale" in params

    loc, scale = params["loc"], params["scale"]
    assert loc.shape == batch[SampleBatch.NEXT_OBS].shape
    assert scale.shape == batch[SampleBatch.NEXT_OBS].shape
    assert loc.dtype == torch.float32
    assert scale.dtype == torch.float32

    parameters = set(module.model.parameters())
    for par in parameters:
        par.grad = None
    loc.mean().backward()
    assert any(p.grad is not None for p in parameters)
    assert all(p.grad is None for p in set(module.parameters()) - parameters)

    for par in parameters:
        par.grad = None
    module.model(batch[SampleBatch.CUR_OBS], batch[SampleBatch.ACTIONS])[
        "scale"
    ].mean().backward()
    assert any(p.grad is not None for p in parameters)
    assert all(p.grad is None for p in set(module.parameters()) - parameters)