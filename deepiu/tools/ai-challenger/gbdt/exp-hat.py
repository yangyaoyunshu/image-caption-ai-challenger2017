#!/usr/bin/env python
#encoding=utf8

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
flags = tf.app.flags
FLAGS = flags.FLAGS

flags.DEFINE_string('input_file', 'ensemble.gbdt.evaluate-inference.txt', '')

import sys
import pickle

from deepiu.util.detector import Detector

class_names = open('/home/gezi/mine/hasky/deepiu/object_detection/data/oid_label_caption.txt').readlines()
class_names = [x.strip() for x in class_names]
print(class_names[0], class_names[1], class_names[10], 'num_classes:', len(class_names))
assert(len(class_names) == 545)

hat_names = set(['帽子', '太阳帽', '牛仔帽', '草帽'])

hat_ids = []
for i in range(len(class_names)):
  if class_names[i] in hat_names:
    hat_ids.append(i) 
hat_ids = set(hat_ids)

print('hat_ids', hat_ids, file=sys.stderr)

detection_dir = '/home/gezi/mine/mount/temp/image-caption/ai-challenger/detection/openimage/faster-rcnn.lowproposals/valid/'


def get_hat_score(detection_result):
  score = 0.
  MAX_INDEX = 1000
  index = MAX_INDEX
  for i in range(detection_result.num):
    if detection_result.classes[i] in hat_ids:
      score += detection_result.scores[i]
      if index == MAX_INDEX:
        index = i
  return score, index

ofile = FLAGS.input_file.replace('.txt', '.detect_hat.txt')

names = ['#img', '#caption']
names += ['detection_hat_score', 'detection_hat_index']

with open(ofile, 'w') as out:
  print('\t'.join(names), file=out)
  for line in open(FLAGS.input_file):
    l = line.strip().split('\t')
    img, caption = l[0], l[1]
    if '帽' in caption:
      detection_path = '%s/%s.pkl' % (detection_dir, img)
      with open(detection_path) as f:
        detection_result = pickle.load(f)
      score, index = get_hat_score(detection_result)
      print(img, caption, score, index, sep='\t', file=out)