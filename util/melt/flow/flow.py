  #!/usr/bin/env python
# ==============================================================================
#          \file   flow.py
#        \author   chenghuige  
#          \date   2016-08-17 10:48:46.141744
#   \Description  
# ==============================================================================

  
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os, sys, traceback
import tensorflow as tf
import tensorflow.contrib.slim as slim
import melt 
import gezi
from melt.utils import logging
import glob

def tf_flow(process_once, num_steps=None, sess=None):
  """
  basic flow for tf records, allow most freedom for usage, if not tfrecords no need for flow
  Args:
  train_once: function with 2 inputs sess and step
  """
  init_op = tf.group(tf.global_variables_initializer(),
                    tf.local_variables_initializer())
  if sess is None:
    sess = tf.InteractiveSession()
  sess.run(init_op)

  coord = tf.train.Coordinator()
  threads = tf.train.start_queue_runners(sess=sess, coord=coord)

  try:
    step = 0
    while not coord.should_stop():
      stop = process_once(sess, step)
      if stop is True:
        print('Early stop running %d stpes'%(step))
        raise tf.errors.OutOfRangeError(None, None,'Early stop running %d stpes'%(step))
      step += 1
      if num_steps and step == num_steps:
        raise tf.errors.OutOfRangeError(None, None, 'Reached max num steps')
  except tf.errors.OutOfRangeError:
    print('Done training for %d steps.' % (step))
  finally:
    coord.request_stop()

  coord.join(threads)
  sess.close()
  return step
 
def _get_model_path(model_dir, save_model):
  if os.path.exists(model_dir + '.index') and os.path.exists(model_dir + '.meta'):
    # input is real model path
    return model_dir
  if not os.path.exists(model_dir):
    if save_model:
      gezi.try_mkdir(model_dir)
    return None
  ckpt = tf.train.get_checkpoint_state(model_dir)
  if ckpt and ckpt.model_checkpoint_path:
    #input valid dir and return latest model
    return os.path.join(model_dir, os.path.basename(ckpt.model_checkpoint_path))
  elif os.path.isdir(model_dir):
    #input valid dir but no models
    return None 
  else:
    #this might be user specified model like ./model/model-100.ckpt
    #the file exists and we NOTICE we do not check if it is valid model file!
    return model_dir

def _get_checkpoint_path(checkpoint_path, step=None, num_steps_per_epoch=None, epoch=None):
  if not num_steps_per_epoch:
    return checkpoint_path
  return '%s-%.2f'%(checkpoint_path, epoch or step / num_steps_per_epoch)

def tf_train_flow(train_once_fn, 
                  model_dir=None,
                  log_dir=None, 
                  max_models_keep=1, 
                  save_interval_seconds=600, 
                  save_interval_steps=1000, 
                  num_epochs=None,
                  num_steps=None, 
                  save_model=True,
                  save_interval_epochs=None, 
                  num_steps_per_epoch=0,
                  restore_from_latest=True,
                  metric_eval_fn=None,
                  init_fn=None,
                  restore_fn=None,
                  restore_scope=None,
                  save_all_scope=False, #TODO save load from restore scope only but svae all
                  variables_to_restore=None,
                  variables_to_save=None, #by default will be the same as variables_to_restore
                  output_collection_names=None, 
                  output_node_names=None,
                  sess=None):
  """
  similary flow as tf_flow, but add model try reload and save
  """
  if sess is None:
    #TODO melt.get_session is global session but may cause non close at last
    sess = melt.get_session()
  logging.info('tf_train_flow start')
  print('max_models_keep:', max_models_keep, file=sys.stderr)
  print('save_interval_seconds:', save_interval_seconds, file=sys.stderr)
  
  #this is usefull for you use another model with another scope, and just load and restore/save initalize your scope vars!
  #this is not for finetune but mainly for like using another model as in predict like this introducing graph other model scope and ignore here

  var_list = None if not restore_scope else tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=restore_scope)
  if not variables_to_restore:
    variables_to_restore = var_list
  if not variables_to_save:
    variables_to_save = variables_to_restore
  if save_all_scope:
    variables_to_save = None
  
  if variables_to_restore is None:
    logging.info('variables_to_restore from %s' % model_dir)
    #load all var in checkpoint try to save all var(might more then original checkpoint) if not specifiy variables_to_save
    varnames_in_checkpoint = melt.get_checkpoint_varnames(model_dir)
    #logging.info('varnames_in_checkpoint: {}'.format(varnames_in_checkpoint))
    variables_to_restore = slim.get_variables_to_restore(include=varnames_in_checkpoint)
  
  ##finally remove global_step since melt.apps.train will handle it!
  variables_to_restore = [v for v in variables_to_restore if not tf.GraphKeys.GLOBAL_STEP in v.name]
  #logging.info('variables_to_restore:{}'.format(variables_to_restore))

  # TODO fixme if step, step2.. and in checkpoint step then here will be step2...
  #print('------------', [v for v in variables_to_restore if 'step' in v.name])
  loader = tf.train.Saver(var_list=variables_to_restore) 

  logging.info('max models to keep {}, keep every {} hours'.format(max_models_keep, save_interval_seconds / 3600.0))
  saver = tf.train.Saver(
    max_to_keep=max_models_keep, 
    keep_checkpoint_every_n_hours=save_interval_seconds / 3600.0,
    var_list=variables_to_save) 
  epoch_saver = tf.train.Saver(var_list=variables_to_save, max_to_keep=1000)
  best_epoch_saver = tf.train.Saver(var_list=variables_to_save) 

  ##TODO for safe restore all init will be ok ?
  #if variables_to_restore is None:
  init_op = tf.group(tf.global_variables_initializer(), #variables_initializer(global_variables())
                    tf.local_variables_initializer()) #variables_initializer(local_variables())
  # else:
  #   init_op = tf.group(tf.variables_initializer(variables_to_restore),
  #                      tf.local_variables_initializer())
  
  ##--mostly this will be fine except for using assistant predictor, initialize again! will make assistant predictor wrong
  ##so assume to all run init op! if using assistant predictor, make sure it use another session
  
  sess.run(init_op)
  
  #melt.init_uninitialized_variables(sess)

  #pre_step means the step last saved, train without pretrained,then -1
  pre_step = -1
  fixed_pre_step = -1  #fixed pre step is for epoch num to be correct if yu change batch size
  #print(model_dir)
  model_path = _get_model_path(model_dir, save_model)
  #print(model_path)
  model_dir = gezi.get_dir(model_dir) #incase you pass ./model/model-ckpt1000 -> ./model
  pre_epoch = None
  if model_path is not None:
    if not restore_from_latest:
      print('using recent but not latest model', file=sys.stderr)
      model_path = melt.recent_checkpoint(model_dir)
    model_name = os.path.basename(model_path)
    timer = gezi.Timer('Loading and training from existing model [%s]' % model_path)
    if restore_fn is not None:
      restore_fn(sess)
    loader.restore(sess, model_path)
    timer.print()
    pre_step = melt.get_model_step(model_path)
    pre_epoch = melt.get_model_epoch(model_path)
    fixed_pre_step = pre_step
    if pre_epoch is not None:
      #like using batch size 32, then reload train using batch size 64
      if abs(pre_step / num_steps_per_epoch - pre_epoch) > 0.1:
        fixed_pre_step = int(pre_epoch * num_steps_per_epoch)
        logging.info('Warning, epoch is diff with pre_step / num_steps_per_epoch:{}, pre_epoch:{},maybe you change batch size and we will adjust to set pre_step as {}'\
          .format(pre_step / num_steps_per_epoch, pre_epoch, fixed_pre_step))
  else:
    print('Train all start step 0', file=sys.stderr)
    #https://stackoverflow.com/questions/40220201/tensorflow-tf-initialize-all-variables-vs-tf-initialize-local-variables
    #tf.initialize_all_variables() is a shortcut to tf.initialize_variables(tf.all_variables()), 
    #tf.initialize_local_variables() is a shortcut to tf.initialize_variables(tf.local_variables()), 
    #which initializes variables in GraphKeys.VARIABLES and GraphKeys.LOCAL_VARIABLE collections, respectively.
    #init_op = tf.group(tf.global_variables_initializer(),
    #                   tf.local_variables_initializer())   
    #[var for var in tf.all_variables() if var.op.name.startswith(restore_scope)] will be the same as tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=restore_scope)
    
    #sess.run(init_op)

    #like use image model, build image graph, reload first train, and then will go to same checkpoint all varaible just restore will ok
    #for finetune from loading other model init
    if init_fn is not None:
      init_fn(sess)
  
  if save_interval_epochs and num_steps_per_epoch and num_steps >= 0:
    epoch_dir = os.path.join(model_dir, 'epoch')
    gezi.try_mkdir(epoch_dir)
  
  coord = tf.train.Coordinator()
  threads = tf.train.start_queue_runners(sess=sess, coord=coord)
  checkpoint_path = os.path.join(model_dir, 'model.ckpt')

  tf.train.write_graph(sess.graph_def, model_dir, 'train.pbtxt')
  only_one_step = False
  try:
    step = start = pre_step +  1
    fixed_step = fixed_pre_step + 1
    #hack just for save one model after load
    if num_steps < 0 or (num_steps and num_steps < step):
      print('just load and resave then exit', file=sys.stderr)
      model_path_ =  _get_checkpoint_path(checkpoint_path, step, num_steps_per_epoch, epoch=pre_epoch)
      saver.save(sess, model_path_, global_step=step)
      melt.freeze_graph(sess, model_path_, step, output_collection_names, output_node_names)
      sess.close()
      exit(0)
    
    if num_epochs < 0:
      only_one_step = True
      print('just run one step', file=sys.stderr)

    early_stop = True #TODO allow config
    num_bad_epochs = 0
    pre_epoch_eval_loss = 1e20
    best_epoch_eval_loss = 1e20
    num_allowed_bad_epochs = 4 #allow 5 non decrease eval loss epochs  before stop
    while not coord.should_stop():
      stop = train_once_fn(sess, step, is_start=(step==start), fixed_step=fixed_step)
      if only_one_step:
        stop = True
      if save_model and step:
        #step 0 is also saved! actually train one step and save
        if step % save_interval_steps == 0:
          timer = gezi.Timer('save model step %d to %s'%(step, checkpoint_path))
          model_path_ = _get_checkpoint_path(checkpoint_path, fixed_step, num_steps_per_epoch)
          saver.save(sess, model_path_, global_step=step)
          melt.freeze_graph(sess, model_path_, step, output_collection_names, output_node_names)
          if log_dir != model_dir:
            assert log_dir
            command = 'rsync -l -r -t %s/* %s' % (log_dir, model_dir) 
            print(command, file=sys.stderr)
            os.system(command)
          timer.print_elapsed()
        #if save_interval_epochs and num_steps_per_epoch and step % (num_steps_per_epoch * save_interval_epochs) == 0:
        #if save_interval_epochs and num_steps_per_epoch and step % num_steps_per_epoch == 0:
        if save_interval_epochs and num_steps_per_epoch and fixed_step % num_steps_per_epoch == 0:
          #epoch = step // num_steps_per_epoch
          epoch = fixed_step // num_steps_per_epoch
          eval_loss = melt.eval_loss()
          if eval_loss:
            #['eval_loss:3.2','eal_accuracy:4.3']
            eval_loss = float(eval_loss.strip('[]').split(',')[0].strip("'").split(':')[-1])
            if os.path.exists(os.path.join(epoch_dir, 'best_eval_loss.txt')):
              with open(os.path.join(epoch_dir, 'best_eval_loss.txt')) as f:
                best_epoch_eval_loss = float(f.readline().split()[-1].strip())
            if eval_loss < best_epoch_eval_loss:
              best_epoch_eval_loss = eval_loss
              logging.info('Now best eval loss is epoch %d eval_loss:%f' % (epoch, eval_loss))
              with open(os.path.join(epoch_dir, 'best_eval_loss.txt'), 'w') as f:
                f.write('%d %d %f\n'%(epoch, step, best_epoch_eval_loss))
              model_path_ = os.path.join(epoch_dir,'model.ckpt-best')
              best_epoch_saver.save(sess, model_path_)
              melt.freeze_graph(sess, model_path_, None, output_collection_names, output_node_names)

            with open(os.path.join(epoch_dir, 'eval_loss.txt'), 'a') as f:
               f.write('%d %d %f\n'%(epoch, step, eval_loss))
            if eval_loss >= pre_epoch_eval_loss:
              num_bad_epochs += 1
              if num_bad_epochs > num_allowed_bad_epochs:
                logging.warning('Evaluate loss not decrease for last %d epochs'% (num_allowed_bad_epochs + 1))
                if not os.path.exists(os.path.join(epoch_dir,'model.ckpt-noimprove')):
                  model_path_ = os.path.join(epoch_dir,'model.ckpt-noimprove')
                  best_epoch_saver.save(sess, model_path_)
                  melt.freeze_graph(sess, model_path_, None, output_collection_names, output_node_names)
                ##-------well remove it since 
                #if early_stop:
                #  stop = True 
            else:
              num_bad_epochs = 0
            pre_epoch_eval_loss = eval_loss
        
        if save_interval_steps and num_steps_per_epoch and fixed_step % int(num_steps_per_epoch * save_interval_epochs) == 0:
          model_path_ = os.path.join(epoch_dir,'model.ckpt-%.2f'%(fixed_step / float(num_steps_per_epoch)))
          epoch_saver.save(sess, model_path_, global_step=step)
          melt.freeze_graph(sess, model_path_, step, output_collection_names, output_node_names)
          #--------do not add step
          # epoch_saver.save(sess, 
          #        os.path.join(epoch_dir,'model.ckpt-%d'%epoch))
      if stop is True:
        print('Early stop running %d stpes'%(step), file=sys.stderr)
        raise tf.errors.OutOfRangeError(None, None,'Early stop running %d stpes'%(step))
      if num_steps and (step + 1) == start + num_steps:
        raise tf.errors.OutOfRangeError(None, None,'Reached max num steps')
      #max_num_epochs = 1000
      max_num_epochs = num_epochs
      if max_num_epochs and num_steps_per_epoch and fixed_step // num_steps_per_epoch >= max_num_epochs:
        raise tf.errors.OutOfRangeError(None, None,'Reached max num epochs of %d'%max_num_epochs)
      step += 1
      fixed_step += 1
  except tf.errors.OutOfRangeError, e:
    if not (step==start) and save_model and step % save_interval_steps != 0:
      model_path_ = _get_checkpoint_path(checkpoint_path, step, num_steps_per_epoch)
      saver.save(sess, model_path_, global_step=step)
      melt.freeze_graph(sess, model_path_, step, output_collection_names, output_node_names)
      if log_dir != model_dir:
        assert log_dir
        command = 'rsync -l -r -t %s/* %s' % (log_dir, model_dir) 
        print(command, file=sys.stderr)
        os.system(command)
    if only_one_step:
      print('Done one step', file=sys.stderr)
      exit(0)
    if metric_eval_fn is not None:
      metric_eval_fn()
    if (num_epochs and fixed_step / num_steps_per_epoch >= num_epochs) or (num_steps and (step + 1) == start + num_steps) :
      print('Done training for %.3f epochs, %d steps.' % (fixed_step / num_steps_per_epoch, step + 1), file=sys.stderr)
      #FIXME becase coord.join seems not work,  RuntimeError: Coordinator stopped with threads still running: Thread-9
      exit(0)
    else:
      print('Should not stop, but stopped at epoch: %.3f'%(fixed_step / num_steps_per_epoch), file=sys.stderr)
      print(traceback.format_exc(), file=sys.stderr)
      raise e
  finally:
    coord.request_stop()

  coord.join(threads, stop_grace_period_secs=5)
  #FIMXE due to use melt.get_session(global not handle del well)
  #Done training for 3090020 steps.
  #Exception TypeError: "'NoneType' object is not callable" in <bound method Session.__del__ of <tensorflow.python.client.session.Session object at 0x7f6cf33cd450>> ignored
  sess.close()

#@TODO not tested yet
def tf_test_flow(test_once, model_dir='./model', 
                 model_name=None, num_epochs=1, num_steps=0,
                 sess=None):
  """
  basic flow for tf records, allow most freedom for usage, if not tfrecords no need for flow
  Args:
  test_once: function with 2 inputs sess and step
  model_dir: can be dir like ./model will fetch lates model in model dir , or be real model path like ./model/model.0.ckpt
  """
  if sess is None:
    sess = tf.InteractiveSession()

  melt.restore(sess, model_dir, model_name)

  if not os.path.isdir(model_dir):
    model_dir = os.path.dirname(model_dir)
  summary_op = tf.merge_all_summaries()
  summary_writer = tf.train.SummaryWriter(model_dir, sess.graph)

  coord = tf.train.Coordinator()
  threads = tf.train.start_queue_runners(sess=sess, coord=coord)
  try:
    step = 0
    while not coord.should_stop():
      test_once(sess, step)
      step += 1
      if num_steps and step == num_steps:
        raise tf.errors.OutOfRangeError(None, None, 'Reached max num steps')
  except tf.errors.OutOfRangeError:
    print('Done testing for %d epochs, %d steps.' % (num_epochs, step))
  finally:
    # When done, ask the threads to stop.
    coord.request_stop()
  # Wait for threads to finish.
  coord.join(threads)
