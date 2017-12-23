conf_path=./prepare/default/app-conf/ai-challenger/seq-basic/
cp $conf_path/conf.py .
source $conf_path/config  

python ./read-records.py \
    --vocab $dir/vocab.txt \
    --input $valid_output_path/'test-*' \
    --batch_size 256 \
    --pre_calc_image_feature 1 \
    --num_negs 1 \
    --neg_left 0 \
    --neg_right 1 \