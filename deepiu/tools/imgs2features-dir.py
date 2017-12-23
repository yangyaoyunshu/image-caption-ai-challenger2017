#!/usr/bin/env python
# ==============================================================================
#          \file   imgs2features.py
#        \author   chenghuige  
#          \date   2017-04-09 00:54:22.224729
#   \Description  
# ==============================================================================

  
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
flags = tf.app.flags
FLAGS = flags.FLAGS
  
#--------- read data
flags.DEFINE_string('image_dir', '', 'input images dir')
flags.DEFINE_string('image_model_name', None, 'InceptionResnetV2 or InceptionV4 or resnet_v2_152.. if not set will get from checkpoint')
flags.DEFINE_integer('image_width', 0, 'default width of inception 299')
flags.DEFINE_integer('image_height', 0, 'default height of inception 299')
flags.DEFINE_string('image_checkpoint_file', '/home/gezi/data/image_model_check_point/inception_resnet_v2_2016_08_30.ckpt', '')
flags.DEFINE_integer('batch_size_', 512, '')
flags.DEFINE_string('feature_name', None, '')
flags.DEFINE_string('image_feature_dir', None, 'output image feature for each pic to this dir')

import sys, os, glob, traceback
import melt

try:
  import cPickle as pickle 
except Exception:
  import pickle

sess = None
images_feed = tf.placeholder(tf.string, [None, ], name='images')
img2feautres_op = None

image_model_name = None
def build_graph(images):
  net = melt.image.get_imagenet_from_checkpoint(FLAGS.image_checkpoint_file)
  assert net is not None, FLAGS.image_checkpoint_file
  global image_model_name
  image_model_name = FLAGS.image_model_name or net.name
  height = FLAGS.image_height or net.default_image_size
  width = FLAGS.image_width or net.default_image_size
  print('image_model_name', image_model_name, 'height', height, 'width', width, file=sys.stderr)
  melt.apps.image_processing.init(image_model_name, feature_name=FLAGS.feature_name)
  return melt.apps.image_processing.image_processing_fn(images,
                                                        height=height,
                                                        width=width)

def init():
  init_op = tf.group(tf.global_variables_initializer(),
                     tf.local_variables_initializer())
  sess.run(init_op)
  # ---load inception model check point file
  init_fn = melt.image.image_processing.create_image_model_init_fn(image_model_name, FLAGS.image_checkpoint_file)
  init_fn(sess)

bad_imgs = []
def imgs2features(imgs, pics):
  try:
    return sess.run(img2feautres_op, feed_dict={images_feed: imgs}), pics
  except Exception:
    features = []
    good_pics = []
    for i, img in enumerate(imgs):
      try:
        features.append(sess.run(img2feautres_op, feed_dict={images_feed : [img]})[0])
        good_pics.append(pics[i])
      except Exception:
        print('!Bad image:', pics[i], file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        bad_imgs.append(pics[i])
    return features, good_pics


def write_features(imgs, pics):
  img_features, pics = imgs2features(imgs, pics)
  for pic, img_feature in zip(pics, img_features):
    #print(pic, '\x01'.join([str(x) for x in img_feature]), sep='\t')
    pic = pic[:pic.rindex('.')] + '.bin'
    ofile = os.path.join(FLAGS.image_feature_dir, pic)
    pickle.dump(img_feature, open(ofile, 'wb'))

def run():
  imgs = []
  pics = []
  if not FLAGS.image_dir:
    FLAGS.image_dir = sys.argv[1]
  all_pics = glob.glob('%s/*'%FLAGS.image_dir)
  print('all_pics:', len(all_pics), file=sys.stderr)
  num_deal = 0
  for pic_path in all_pics:
    #print(pic_path, file=sys.stderr)
    imgs.append(melt.image.read_image(pic_path))
    pic = pic_path[pic_path.rindex('/') + 1:]
    pics.append(pic)
    if len(imgs) == FLAGS.batch_size_:
      write_features(imgs, pics)
      num_deal += len(pics)
      print('convert: %d %f'%(num_deal, num_deal / len(all_pics)), file=sys.stderr)
      imgs = []
      pics = []
  if imgs:
    write_features(imgs, pics)
    num_deal += len(pics)
    print('convert: %d %f'%(num_deal, num_deal / len(all_pics)), file=sys.stderr)

  print(bad_imgs, file=sys.stderr)
  print('All %d, Bad %d, BadRatio: %f'%(len(all_pics), len(bad_imgs), len(bad_imgs) / len(all_pics)), file=sys.stderr)

def main(_):
  command = 'mkdir -p %s' % FLAGS.image_feature_dir 
  print(command, file=sys.stderr)
  os.system(command)

  global img2feautres_op 
  img2feautres_op = build_graph(images_feed)

  global sess
  sess = tf.Session()
  
  init()
  run()


if __name__ == '__main__':
  tf.app.run()