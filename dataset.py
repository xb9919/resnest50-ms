# Copyright 2020 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""
create train or eval dataset.
"""
import multiprocessing
import os
import mindspore.common.dtype as mstype
import mindspore.dataset as ds
import mindspore.dataset.vision.c_transforms as C
import mindspore.dataset.transforms.c_transforms as C2
from mindspore.communication.management import init, get_rank, get_group_size

def create_dataset(dataset_path, do_train, repeat_num=1, batch_size=32, train_image_size=224, eval_image_size=224,
                    target="GPU", distribute=True, enable_cache=False, cache_session_id=None):
    """
    create a train or eval imagenet2012 dataset for resnet50

    Args:
        dataset_path(string): the path of dataset.
        do_train(bool): whether dataset is used for train or eval.
        repeat_num(int): the repeat times of dataset. Default: 1
        batch_size(int): the batch size of dataset. Default: 32
        target(str): the device target. Default: Ascend
        distribute(bool): data for distribute or not. Default: False
        enable_cache(bool): whether tensor caching service is used for eval. Default: False
        cache_session_id(int): If enable_cache, cache session_id need to be provided. Default: None

    Returns:
        dataset
    """
    device_num, rank_id = _get_rank_info(distribute)

    ds.config.set_prefetch_size(64)
    if device_num == 1:
        data_set = ds.ImageFolderDataset(dataset_path, num_parallel_workers=get_num_parallel_workers(12), shuffle=True)
    else:
        data_set = ds.ImageFolderDataset(dataset_path, num_parallel_workers=get_num_parallel_workers(12), shuffle=True,
                                         num_shards=device_num, shard_id=rank_id)

    mean = [0.485 * 255, 0.456 * 255, 0.406 * 255]
    std = [0.229 * 255, 0.224 * 255, 0.225 * 255]

    # define map operations
    if do_train:
        trans = [
            C.RandomCropDecodeResize(train_image_size, scale=(0.08, 1.0), ratio=(0.75, 1.333)),
            C.RandomHorizontalFlip(prob=0.5),
            C.Normalize(mean=mean, std=std),
            C.HWC2CHW()
        ]
    else:
        trans = [
            C.Decode(),
            C.Resize(256),
            C.CenterCrop(eval_image_size),
            C.Normalize(mean=mean, std=std),
            C.HWC2CHW()
        ]

    type_cast_op = C2.TypeCast(mstype.int32)

    data_set = data_set.map(operations=trans, input_columns="image", num_parallel_workers=get_num_parallel_workers(12))
    # only enable cache for eval
    if do_train:
        enable_cache = False
    if enable_cache:
        if not cache_session_id:
            raise ValueError("A cache session_id must be provided to use cache.")
        eval_cache = ds.DatasetCache(session_id=int(cache_session_id), size=0)
        data_set = data_set.map(operations=type_cast_op, input_columns="label",
                                num_parallel_workers=get_num_parallel_workers(12),
                                cache=eval_cache)
    else:
        data_set = data_set.map(operations=type_cast_op, input_columns="label",
                                num_parallel_workers=get_num_parallel_workers(12))

    # apply batch operations
    data_set = data_set.batch(batch_size, drop_remainder=True)

    # apply dataset repeat operation
    data_set = data_set.repeat(repeat_num)

    return data_set


def _get_rank_info():
    """
    get rank size and rank id
    """
    rank_size = int(os.environ.get("RANK_SIZE", 1))

    if rank_size > 1:
        rank_size = get_group_size()
        rank_id = get_rank()
    else:
        rank_size = 1
        rank_id = 0

    return rank_size, rank_id

def _get_rank_info(distribute):
    """
    get rank size and rank id
    """
    if distribute:
        init()
        rank_id = get_rank()
        device_num = get_group_size()
    else:
        rank_id = 0
        device_num = 1
    return device_num, rank_id

def get_num_parallel_workers(num_parallel_workers):
    """
    Get num_parallel_workers used in dataset operations.
    If num_parallel_workers > the real CPU cores number, set num_parallel_workers = the real CPU cores number.
    """
    cores = multiprocessing.cpu_count()
    if isinstance(num_parallel_workers, int):
        if cores < num_parallel_workers:
            print("The num_parallel_workers {} is set too large, now set it {}".format(num_parallel_workers, cores))
            num_parallel_workers = cores
    else:
        print("The num_parallel_workers {} is invalid, now set it {}".format(num_parallel_workers, min(cores, 8)))
        num_parallel_workers = min(cores, 8)
    return num_parallel_workers
