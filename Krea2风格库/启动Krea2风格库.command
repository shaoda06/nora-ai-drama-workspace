#!/bin/zsh
cd -- "${0:A:h}"
python3 Krea2_更新工具/server.py
if [[ $? -ne 0 ]]; then
  printf '\n启动失败。请确认已安装 Python 3，且 8876 端口未被占用。\n按回车关闭。'
  read
fi
