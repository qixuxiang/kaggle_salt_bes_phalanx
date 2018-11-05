from copy import deepcopy
import os
import numpy as np
import pandas as pd
from tqdm import tqdm

import cv2
import torch
from torch.utils.data import Dataset

from transform import *

train_root = '../data/train/'
test_root = '../data/test/'

train_id = pd.read_csv('../data/train.csv')['id'].values
depth_id = pd.read_csv('../data/depths.csv')['id'].values
test_id = np.setdiff1d(depth_id, train_id)


def add_depth_channels(image_tensor):
    _, h, w = image_tensor.size()
    image = torch.zeros([3, h, w])
    image[0] = image_tensor
    for row, const in enumerate(np.linspace(0, 1, h)):
        image[1, row, :] = const
    image[2] = image[0] * image[1]
    return image


def train_aug(image, mask):
    if np.random.rand() < 0.5:
        image, mask = do_horizontal_flip2(image, mask)

    if np.random.rand() < 0.5:
        c = np.random.choice(3)
        if c == 0:
            image, mask = do_random_shift_scale_crop_pad2(image, mask, 0.2)

        if c == 1:
            image, mask = do_horizontal_shear2(image, mask, dx=np.random.uniform(-0.07, 0.07))

        if c == 2:
            image, mask = do_shift_scale_rotate2(image, mask, dx=0, dy=0, scale=1, angle=np.random.uniform(0, 15))

    if np.random.rand() < 0.5:
        c = np.random.choice(2)
        if c == 0:
            image = do_brightness_shift(image, np.random.uniform(-0.1, +0.1))
        if c == 1:
            image = do_brightness_multiply(image, np.random.uniform(1 - 0.08, 1 + 0.08))

    return image, mask


class SaltDataset(Dataset):
    def __init__(self, image_list, mask_list=None, is_train=False, is_val=False, is_tta=False, is_semi=False,
                 fine_size=202, pad_left=0, pad_right=0):
        self.imagelist = image_list
        self.masklist = mask_list
        self.is_train = is_train
        self.is_val = is_val
        self.is_tta = is_tta
        self.is_semi = is_semi
        self.fine_size = fine_size
        self.pad_left = pad_left
        self.pad_right = pad_right

    def __len__(self):
        return len(self.imagelist)

    def __getitem__(self, idx):
        image = deepcopy(self.imagelist[idx])

        if self.is_train:
            mask = deepcopy(self.masklist[idx])

            image, mask = train_aug(image, mask)
            label = np.where(mask.sum() == 0, 1.0, 0.0).astype(np.float32)

            if self.fine_size != image.shape[0]:
                image, mask = do_resize2(image, mask, self.fine_size, self.fine_size)

            if self.pad_left != 0:
                image, mask = do_center_pad2(image, mask, self.pad_left, self.pad_right)

            image = image.reshape(1, self.fine_size + self.pad_left + self.pad_right,
                                  self.fine_size + self.pad_left + self.pad_right)
            mask = mask.reshape(1, self.fine_size + self.pad_left + self.pad_right,
                                self.fine_size + self.pad_left + self.pad_right)
            image, mask = torch.from_numpy(image), torch.from_numpy(mask)
            image = add_depth_channels(image)
            image.requires_grad_(True)
            return image, mask, torch.from_numpy(label)

        if self.is_val:
            mask = deepcopy(self.masklist[idx])
            if self.fine_size != image.shape[0]:
                image, mask = do_resize2(image, mask, self.fine_size, self.fine_size)
            if self.pad_left != 0:
                image = do_center_pad(image, self.pad_left, self.pad_right)

            image = image.reshape(1, self.fine_size + self.pad_left + self.pad_right,
                                  self.fine_size + self.pad_left + self.pad_right)
            mask = mask.reshape(1, self.fine_size, self.fine_size)
            image, mask = torch.from_numpy(image), torch.from_numpy(mask)
            image = add_depth_channels(image)
            image.requires_grad_(True)
            return image, mask

        if self.is_tta:
            image = cv2.flip(image, 1)
        if self.fine_size != image.shape[0]:
            image = cv2.resize(image, dsize=(self.fine_size, self.fine_size))
        if self.pad_left != 0:
            image = do_center_pad(image, self.pad_left, self.pad_right)

        image = image.reshape(1, self.fine_size + self.pad_left + self.pad_right,
                              self.fine_size + self.pad_left + self.pad_right)
        image = torch.from_numpy(image)
        image = add_depth_channels(image)
        return image


def trainImageFetch(images_id):
    image_train = np.zeros((images_id.shape[0], 101, 101), dtype=np.float32)
    mask_train = np.zeros((images_id.shape[0], 101, 101), dtype=np.float32)

    for idx, image_id in tqdm(enumerate(images_id), total=images_id.shape[0]):
        image_path = '../data/train/images/' + image_id + '.png'
        mask_path = '../data/train/masks/' + image_id + '.png'

        image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
        image_train[idx] = image
        mask_train[idx] = mask

    return image_train, mask_train


def semi_trainImageFetch(pseudo_path, list_id=None):
    if list_id == None:
        images_id = os.listdir(pseudo_path)
    else:
        images_id = list_id
        
    image_train = np.zeros((len(images_id), 101, 101), dtype=np.float32)
    mask_train = np.zeros((len(images_id), 101, 101), dtype=np.float32)

    for idx, image_id in tqdm(enumerate(images_id)):
        image_path = '../data/test/images/' + image_id
        mask_path = pseudo_path + image_id

        image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
        image_train[idx] = image
        mask_train[idx] = mask

    return image_train, mask_train


def testImageFetch(test_id):
    image_test = np.zeros((len(test_id), 101, 101), dtype=np.float32)

    for n, image_id in tqdm(enumerate(test_id), total=len(test_id)):
        image_path = '/test_data/' + image_id + '.png'

        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
        image_test[n] = img

    return image_test