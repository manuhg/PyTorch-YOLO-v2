from __future__ import division
import time
import torch 
import torch.nn as nn
from torch.autograd import Variable
import numpy as np
import cv2 
from util import *
import argparse
import os 
import os.path as osp
from darknet import Darknet
from preprocess import prep_image, inp_to_image
import pandas as pd
import random 
import pickle as pkl

num_classes=0

class test_net(nn.Module):
    def __init__(self, num_layers, input_size):
        super(test_net, self).__init__()
        self.num_layers= num_layers
        self.linear_1 = nn.Linear(input_size, 5)
        self.middle = nn.ModuleList([nn.Linear(5,5) for x in range(num_layers)])
        self.output = nn.Linear(5,2)
    
    def forward(self, x):
        x = x.view(-1)
        fwd = nn.Sequential(self.linear_1, *self.middle, self.output)
        return fwd(x)
        
def get_test_input(input_dim, CUDA):
    img = cv2.imread("dog-cycle-car.png")
    img = cv2.resize(img, (input_dim, input_dim)) 
    img_ =  img[:,:,::-1].transpose((2,0,1))
    img_ = img_[np.newaxis,:,:,:]/255.0
    img_ = torch.from_numpy(img_).float()
    img_ = Variable(img_)
    
    if CUDA:
        img_ = img_.cuda()
    num_classes
    return img_



def load_yolov2(image,output_file,dataset='coco',threshold=0.5,nms_thresh=0.4):
    batch_size = 1
    confidence = threshold
    start = 0
    global num_classes
    imlist = image
    output_file_names = [output_file]

    CUDA = torch.cuda.is_available()
    
    if dataset == "pascal":
        inp_dim = 416
        num_classes = 20
        classes = load_classes('data/voc.names')
        weightsfile = 'yolov2-voc.weights'
        cfgfile = "cfg/yolo-voc.cfg"

    
    elif dataset == "coco":
        inp_dim = 544
        num_classes = 80
        classes = load_classes('data/coco.names')
        weightsfile = 'yolov2.weights'
        cfgfile = "cfg/yolo.cfg" 
        
    else: 
        print("Invalid dataset")
        exit()

        
    stride = 32

    #Set up the neural network
    print("Loading network.....")
    model = Darknet(cfgfile)
    model.load_weights(weightsfile)
    print("Network successfully loaded")
    
    
    #If there's a GPU availible, put the model on GPU
    if CUDA:
        model.cuda()
    
    model(get_test_input(inp_dim, CUDA))
    #Set the model in evaluation mode
    model.eval()
    
    read_dir = time.time()
    #Detection phase
    load_batch = time.time()
    batches = list(map(prep_image, imlist, [inp_dim for x in range(len(imlist))]))
    im_batches = [x[0] for x in batches]
    orig_ims = [x[1] for x in batches]
    im_dim_list = [x[2] for x in batches]
    im_dim_list = torch.FloatTensor(im_dim_list).repeat(1,2)
    
    if CUDA:
        im_dim_list = im_dim_list.cuda()
    
    leftover = 0
    
    if (len(im_dim_list) % batch_size):
        leftover = 1
        
    if batch_size != 1:
        num_batches = len(imlist) // batch_size + leftover            
        im_batches = [torch.cat((im_batches[i*batch_size : min((i +  1)*batch_size,
                            len(im_batches))]))  for i in range(num_batches)]        


    i = 0
    
    output = torch.FloatTensor(1, 8)
    write = False
#    model(get_test_input(inp_dim, CUDA))
    
    start_det_loop = time.time()
    for batch in im_batches:
        #load the image 
        start = time.time()
        if CUDA:
            batch = batch.cuda()
       
        prediction = model(Variable(batch, volatile = True))
        
        prediction = prediction.data 
        
        
        
        #Apply offsets to the result predictions
        #Tranform the predictions as described in the YOLO paper
        #flatten the prediction vector 
        # B x (bbox cord x no. of anchors) x grid_w x grid_h --> B x bbox x (all the boxes) 
        # Put every proposed box as a row.
        #get the boxes with object confidence > threshold
        #Convert the cordinates to absolute coordinates
        
        prediction = predict_transform(prediction, inp_dim, stride, model.anchors, num_classes, confidence, CUDA)
        
            
        if type(prediction) == int:
            i += 1
            continue
        
        #perform NMS on these boxes, and save the results 
        #I could have done NMS and saving seperately to have a better abstraction
        #But both these operations require looping, hence 
        #clubbing these ops in one loop instead of two. 
        #loops are slower than vectorised operations. 
        
        prediction = write_results(prediction, num_classes, nms = True, nms_conf = nms_thresh)
        
        
        end = time.time()
        
                    
#        print(end - start)

            

        prediction[:,0] += i*batch_size
        
    
            
        
          
        if not write:
            output = prediction
            write = 1
        else:
            output = torch.cat((output,prediction))
            

        for image in imlist[i*batch_size: min((i +  1)*batch_size, len(imlist))]:
            im_id = imlist.index(image)
            objs = [classes[int(x[-1])] for x in output if int(x[0]) == im_id]
            print("{0:20s} predicted in {1:6.3f} seconds".format(image.split("/")[-1], (end - start)/batch_size))
            print("{0:20s} {1:s}".format("Objects Detected:", " ".join(objs)))
            print("----------------------------------------------------------")
        i += 1

        
        if CUDA:
            torch.cuda.synchronize()
    
    
    output_recast = time.time()
    output[:,1:5] = torch.clamp(output[:,1:5], 0.0, float(inp_dim))
        
    im_dim_list = torch.index_select(im_dim_list, 0, output[:,0].long())/inp_dim
    output[:,1:5] *= im_dim_list
    
    
    class_load = time.time()

    colors = pkl.load(open("pallete", "rb"))
    
    
    draw = time.time()


    def write(x, batches, results):
        c1 = tuple(x[1:3].int())
        c2 = tuple(x[3:5].int())
        img = results[int(x[0])]
        cls = int(x[-1])
        label = "{0}".format(classes[cls])
        color = random.choice(colors)
        cv2.rectangle(img, c1, c2,color, 1)
        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_PLAIN, 1 , 1)[0]
        c2 = c1[0] + t_size[0] + 3, c1[1] + t_size[1] + 4
        cv2.rectangle(img, c1, c2,color, -1)
        cv2.putText(img, label, (c1[0], c1[1] + t_size[1] + 4), cv2.FONT_HERSHEY_PLAIN, 1, [225,255,255], 1);
        return img
    
            
    list(map(lambda x: write(x, im_batches, orig_ims), output))
      
    #det_names = pd.Series(imlist).apply(lambda x: "{}/det_{}".format(args.det,x.split("/")[-1]))
    det_names = output_file_names
    
    list(map(cv2.imwrite, det_names, orig_ims))
    
    end = time.time()
    
    print()
    print("SUMMARY")
    print("----------------------------------------------------------")
    print("{:25s}: {}".format("Task", "Time Taken (in seconds)"))
    print()
    print("{:25s}: {:2.3f}".format("Reading addresses", load_batch - read_dir))
    print("{:25s}: {:2.3f}".format("Loading batch", start_det_loop - load_batch))
    print("{:25s}: {:2.3f}".format("Detection (" + str(len(imlist)) +  " images)", output_recast - start_det_loop))
    print("{:25s}: {:2.3f}".format("Output Processing", class_load - output_recast))
    print("{:25s}: {:2.3f}".format("Drawing Boxes", end - draw))
    print("{:25s}: {:2.3f}".format("Average time_per_img", (end - load_batch)/len(imlist)))
    print("----------------------------------------------------------")

    
    torch.cuda.empty_cache()
        
        
            
load_yolov2(osp.join(osp.realpath('.')+'imgs/messi.jpg'),'predictions.jpg')
