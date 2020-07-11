import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Uniform
from .color_utils import *
import kornia

class colorMask(nn.Module):
    def __init__(self, imageSize, nc, nz, datasetmean, datasetstd, neurons=6):
        super(colorMask, self).__init__()
        self.imageSize = imageSize
        self.nc = nc
        self.nz = nz
        self.mean = torch.tensor(datasetmean)
        self.std = torch.tensor(datasetstd)
        self.deconv1 = nn.ConvTranspose2d(self.nz, 8, 8, 1, 0, bias=False)
        self.deconv2 = nn.ConvTranspose2d(8, 16, 2, 2, 0, bias=False)
        self.deconv3 = nn.ConvTranspose2d(16, 32, 2, 2, 0, bias=False)
        self.deconv4 = nn.ConvTranspose2d(32, self.nc, 1, 1, 0, bias=False)
        self.lin1 = nn.Linear(6, neurons)
        self.lin2 = nn.Linear(neurons, 10 * neurons)
        self.lin3 = nn.Linear(10*neurons, 4)
        self.drop = nn.Dropout(0.2)
        self.buffer_in = torch.Tensor()
        self.buffer_out = torch.Tensor()

    def get_mask(self, noise):
        mask = self.deconv1(noise.unsqueeze(-1).unsqueeze(-1))
        mask = self.drop(mask)
        mask = self.deconv2(mask)
        mask = self.drop(mask)
        mask = self.deconv3(mask)
        mask = self.drop(mask)
        mask = self.deconv4(mask)
        mask = torch.tanh(mask)

        return mask

    def get_color_parameters(self, noise):
        colorparams = F.relu(self.lin1(noise))
        colorparams = self.drop(colorparams)
        colorparams = F.relu(self.lin2(colorparams))
        colorparams = self.drop(colorparams)
        colorparams = self.lin3(colorparams)
        colorparams = torch.tanh(colorparams)

        return colorparams

    def forward(self, x):
        if self.mean.device != x.device:
            self.mean = self.mean.to(x.device)
            self.std = self.std.to(x.device)        
        # noise
        bs = x.shape[0]
        self.uniform = Uniform(low=-torch.ones(bs, self.nz).to(x.device), high=torch.ones(bs, self.nz).to(x.device))
        noise = self.uniform.rsample()
        # compute mask
        mask = self.get_mask(noise)
        masks = mask / self.std.view(1, 3, 1, 1)
        # Bring images back to [-1:1]
        x = x * self.std.view(1, 3, 1, 1)
        # apply mask
        x = torch.clamp(mask + x, min=-1, max=1) / self.std.view(1, 3, 1, 1)
        # noise 2
        self.uniform2 = Uniform(low=-torch.ones(bs, 6).to(x.device), high=torch.ones(bs, 6).to(x.device))
        noise2 = self.uniform2.rsample()
        # get color transformations parameters
        colorsparams = self.get_color_parameters(noise2)
        nb_transform = 4
        transform_order = torch.randperm(nb_transform).to(x.device)
        # bring images back to [0:1]
        x = x + self.mean.view(1, 3, 1, 1)
        for i in range(nb_transform):
            if transform_order[i] == 0:
                x = adjust_brightness(x, 1 + colorsparams[:, 0].squeeze(-1))
            elif transform_order[i] == 1:
                x = adjust_contrast(x, colorsparams[:, 1].squeeze(-1))
            elif transform_order[i] == 2:
                x = adjust_saturation(x, 1 + colorsparams[:, 2].squeeze(-1))
            elif transform_order[i] == 3:
                x = adjust_hue(x, colorsparams[:, 3].squeeze(-1) * 0.5)
        # Restandardize images
        x = (x - self.mean.view(1, 3, 1, 1)) / self.std.view(1, 3, 1, 1)

        # if self.buffer_in.size()[0] == 0:
        #     self.buffer_in = smp.clone().detach()
        # else:
        #     self.buffer_in = torch.cat((self.buffer_in, smp.clone().detach()))
        if self.buffer_out.size()[0] == 0:
            self.buffer_out = colorsparams.clone().detach()
        else:
            self.buffer_out = torch.cat((self.buffer_out, colorsparams.clone().detach()))

        return x, masks, self.buffer_out