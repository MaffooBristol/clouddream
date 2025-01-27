#!/usr/bin/env python

# imports and basic notebook setup
from cStringIO import StringIO
import numpy as np
import scipy.ndimage as nd
import PIL.Image
import json
from IPython.display import clear_output, Image, display
from google.protobuf import text_format

import caffe

import sys, argparse

parser = argparse.ArgumentParser(description='')
parser.add_argument('infile')
parser.add_argument('outfile', default='output.jpg')
parser.add_argument('--step-size', type=float, default=1.5)
parser.add_argument('--jitter', type=int, default=32)
parser.add_argument('--iterations', type=int, default=10)
parser.add_argument('--octaves', type=int, default=4)
parser.add_argument('--octave-scale', type=float, default=1.4)
parser.add_argument('--resamples', type=int, default=0)
parser.add_argument('--max-width', type=int)

args = parser.parse_args()

inputFile = args.infile if args.infile else 'input.jpg'
outputFile = args.outfile if args.outfile else 'output.jpg'

stepSize = args.step_size
jitter = args.jitter

iterations = args.iterations
octaves = args.octaves
octaveScale = args.octave_scale

resamples = args.resamples

def showarray(a, fmt='jpeg'):
    a = np.uint8(np.clip(a, 0, 255))
    f = StringIO()
    PIL.Image.fromarray(a).save(f, fmt)
    display(Image(data=f.getvalue()))

with open("settings.json") as json_file:
    json_data = json.load(json_file)
    #print()


model_path = '../caffe/models/bvlc_googlenet/' # substitute your path here
net_fn   = model_path + 'deploy.prototxt'
param_fn = model_path + 'bvlc_googlenet.caffemodel'

# Patching model to be able to compute gradients.
# Note that you can also manually add "force_backward: true" line to "deploy.prototxt".
model = caffe.io.caffe_pb2.NetParameter()
text_format.Merge(open(net_fn).read(), model)
model.force_backward = True
open('tmp.prototxt', 'w').write(str(model))

net = caffe.Classifier('tmp.prototxt', param_fn,
                       mean = np.float32([104.0, 116.0, 122.0]), # ImageNet mean, training set dependent
                       channel_swap = (2,1,0)) # the reference model has channels in BGR order instead of RGB

# a couple of utility functions for converting to and from Caffe's input image layout
def preprocess(net, img):
    return np.float32(np.rollaxis(img, 2)[::-1]) - net.transformer.mean['data']
def deprocess(net, img):
    return np.dstack((img + net.transformer.mean['data'])[::-1])

def make_step(net, step_size=stepSize, end='inception_4c/output', jitter=jitter, clip=True):
    '''Basic gradient ascent step.'''

    src = net.blobs['data'] # input image is storred in Net's 'data' blob
    dst = net.blobs[end]

    ox, oy = np.random.randint(-jitter, jitter+1, 2)
    src.data[0] = np.roll(np.roll(src.data[0], ox, -1), oy, -2) # apply jitter shift
            
    net.forward(end=end)
    dst.diff[:] = dst.data  # specify the optimiation objective
    net.backward(start=end)
    g = src.diff[0]
    # apply normaized ascent step to the input image
    src.data[:] += step_size/np.abs(g).mean() * g

    src.data[0] = np.roll(np.roll(src.data[0], -ox, -1), -oy, -2) # unshift image
            
    if clip:
        bias = net.transformer.mean['data']
        src.data[:] = np.clip(src.data, -bias, 255-bias)    

def deepdream(net, base_img, iter_n=iterations, octave_n=octaves, octave_scale=octaveScale, end='inception_4c/output', clip=True, **step_params):
    # prepare base images for all octaves
    octaves = [preprocess(net, base_img)]
    for i in xrange(octave_n-1):
        octaves.append(nd.zoom(octaves[-1], (1, 1.0/octave_scale,1.0/octave_scale), order=1))
    
    src = net.blobs['data']
    detail = np.zeros_like(octaves[-1]) # allocate image for network-produced details
    for octave, octave_base in enumerate(octaves[::-1]):
        h, w = octave_base.shape[-2:]
        if octave > 0:
            # upscale details from the previous octave
            h1, w1 = detail.shape[-2:]
            detail = nd.zoom(detail, (1, 1.0*h/h1,1.0*w/w1), order=1)

        src.reshape(1,3,h,w) # resize the network's input image size
        src.data[0] = octave_base+detail
        for i in xrange(iter_n):
            make_step(net, end=end, clip=clip, **step_params)
            
            # visualization
            vis = deprocess(net, src.data[0])
            if not clip: # adjust image contrast if clipping is disabled
                vis = vis*(255.0/np.percentile(vis, 99.98))
            #showarray(vis)
            print octave, i, end, vis.shape
            clear_output(wait=True)
            
        # extract details produced on the current octave
        detail = src.data[0]-octave_base
    # returning the resulting image
    return deprocess(net, src.data[0])


maxwidth = args.max_width if 'max-width' in args else json_data['maxwidth']
img = PIL.Image.open(inputFile)
width = img.size[0]

if width > maxwidth:
    wpercent = (maxwidth/float(img.size[0]))
    hsize = int((float(img.size[1])*float(wpercent)))
    img = img.resize((maxwidth,hsize), PIL.Image.ANTIALIAS)

img = np.float32(img)

frame = img
frame_i = 0

frame = deepdream(net, frame, end=json_data['layer'])
#frame = deepdream(net, img, end='inception_3b/5x5_reduce')
#frame = deepdream(net, img, end='conv2/3x3')

PIL.Image.fromarray(np.uint8(frame)).save(outputFile)

if resamples > 0:

	h, w = frame.shape[:2]
	s = 0.05 # scale coefficient
	for i in xrange(resamples):
	    frame = deepdream(net, frame)
	    PIL.Image.fromarray(np.uint8(frame)).save("frames/%04d.jpg"%frame_i)
	    frame = nd.affine_transform(frame, [1-s,1-s,1], [h*s/2,w*s/2,0], order=1)
	    frame_i += 1
