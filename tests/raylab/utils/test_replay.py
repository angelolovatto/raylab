from functools import partial

import numpy as np
import pytest
from ray.rllib import SampleBatch

from raylab.utils.debug import fake_batch
from raylab.utils.replay_buffer import ListReplayBuffer
from raylab.utils.replay_buffer import NumpyReplayBuffer
from raylab.utils.replay_buffer import ReplayField


@pytest.fixture(params=(ListReplayBuffer, NumpyReplayBuffer))
def replay_cls(request, obs_space, action_space):
    cls = request.param
    if issubclass(cls, NumpyReplayBuffer):
        return partial(cls, obs_space=obs_space, action_space=action_space)
    return cls


@pytest.fixture
def size():
    return int(1e4)


@pytest.fixture
def replay(replay_cls, size):
    return replay_cls(size=size)


@pytest.fixture
def sample_batch(obs_space, action_space):
    return fake_batch(obs_space, action_space, batch_size=10)


@pytest.fixture(params=[(), ("a",), ("a", "b")])
def extra_fields(request):
    return (ReplayField(n) for n in request.param)


@pytest.fixture
def extra_replay(replay, extra_fields):
    replay.add_fields(*extra_fields)
    return replay


def test_size_zero(replay_cls):
    replay_cls(size=0)


def test_replay_init(extra_replay, extra_fields):
    replay = extra_replay

    assert all(
        k in {f.name for f in replay.fields}
        for k in [
            SampleBatch.CUR_OBS,
            SampleBatch.ACTIONS,
            SampleBatch.NEXT_OBS,
            SampleBatch.REWARDS,
            SampleBatch.DONES,
        ]
    )
    assert all(f in replay.fields for f in extra_fields)
    assert replay._maxsize == int(1e4)


@pytest.fixture
def filled_replay(replay, sample_batch):
    if isinstance(replay, ListReplayBuffer):
        for row in sample_batch.rows():
            replay.add(row)
    else:
        replay.add(sample_batch)
    return replay


def test_all_samples(filled_replay, sample_batch):
    replay = filled_replay
    buffer = replay.all_samples()
    assert isinstance(buffer, SampleBatch)
    assert all(np.allclose(sample_batch[k], buffer[k]) for k in sample_batch.keys())


@pytest.fixture
def numpy_replay(obs_space, action_space, size):
    return NumpyReplayBuffer(obs_space, action_space, size)


@pytest.fixture(params=(0, np.array([0, 2]), slice(0, 2)), ids=lambda x: f"IDX:{x}")
def idx(request):
    return request.param


def test_sample(numpy_replay, sample_batch):
    replay = numpy_replay
    replay.add(sample_batch)
    batch_size = len(replay) // 10

    replay.seed(42)
    samples = replay.sample(batch_size)
    assert isinstance(samples, SampleBatch)

    replay.seed(42)
    samples_ = replay.sample(batch_size)
    assert all([np.allclose(samples[k], samples_[k]) for k in samples.keys()])


def test_getitem(numpy_replay, sample_batch, idx):
    replay = numpy_replay
    replay.add(sample_batch)

    batch = replay[idx]
    assert isinstance(batch, dict)
    assert all(
        [np.allclose(batch[k], sample_batch[k][idx]) for k in sample_batch.keys()]
    )
