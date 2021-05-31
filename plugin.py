# -*- coding: utf-8 -*-
#########################################################
# python
import os
import traceback

# third-party
import requests
from flask import Blueprint, request, send_file, redirect, render_template

# sjva 공용
from framework import app, path_data, check_api, py_urllib, SystemModelSetting
from framework.logger import get_logger
from framework.util import Util
from framework.common.plugin import get_model_setting, Logic, default_route

# 패키지
#########################################################
use_av = True
use_setting = True

class P(object):
    package_name = __name__.split('.')[0]
    logger = get_logger(package_name)
    blueprint = Blueprint(package_name, package_name, url_prefix='/%s' %  package_name, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

    try:
        import sqlite3
        conn = sqlite3.connect(os.path.join(path_data, 'db', '{package_name}.db'.format(package_name=package_name)))
        cursor = conn.cursor()
        key = ('use_av',)
        cursor.execute('SELECT value from scmanager_setting where key = ?', key)
        value = cursor.fetchone()
        if value[0] == u"True": use_av = True
        else: use_av = False
        key = ('use_setting',)
        cursor.execute('SELECT value from scmanager_setting where key = ?', key)
        value = cursor.fetchone()
        if value[0] == u"True": use_setting = True
        else: use_setting = False
        conn.close()
    except Exception as e: 
        logger.error('failed to get user setting')
        logger.error('Exception:%s', e)
        logger.error(traceback.format_exc())
        conn.close()
        use_av = True
        use_setting = True

    if use_av:
        menu = {
            'main' : [package_name, u'GD바로가기관리'],
            'sub' : [
                ['scmbase', u'라이브러리관리'], ['tv', 'TV목록'], ['mv', '영화목록'], ['av', 'AV목록'], ['log', u'로그']
            ],
            'category' : 'service',
            'sub2' : {
                'scmbase': [
                    ['setting',u'설정'],['rulelist', u'경로규칙목록']
                ],
            },
        }
    else:
        if use_setting:
            menu = {
                'main' : [package_name, u'GD바로가기관리'],
                'sub' : [
                    ['scmbase', u'라이브러리관리'], ['tv', 'TV목록'], ['mv', '영화목록'], ['log', u'로그']
                ],
                'category' : 'service',
                'sub2' : {
                    'scmbase': [
                        ['setting',u'설정'],['rulelist', u'경로규칙목록']
                    ],
                },
            }
        else:
            menu = {
                'main' : [package_name, u'GD바로가기관리'],
                'sub' : [
                    ['scmbase', u'라이브러리관리'], ['tv', 'TV목록'], ['mv', '영화목록'], ['log', u'로그']
                ],
                'category' : 'service',
                'sub2' : {
                    'scmbase': [
                        ['rulelist', u'경로규칙목록']
                    ],
                },
            }


    plugin_info = {
        'version' : '0.3.0.1',
        'name' : package_name,
        'category_name' : 'service',
        'icon' : '',
        'developer' : u'orial',
        'description' : u'Gdrive shorcut manager for SJVA Plugin',
        'home' : 'https://github.com/byorial/%s' % package_name,
        'more' : '',
    }
    ModelSetting = get_model_setting(package_name, logger)
    logic = None
    module_list = None
    home_module = 'scmbase'


def initialize():
    try:
        global use_av

        app.config['SQLALCHEMY_BINDS'][P.package_name] = 'sqlite:///%s' % (os.path.join(path_data, 'db', '{package_name}.db'.format(package_name=P.package_name)))
        from framework.util import Util
        Util.save_from_dict_to_json(P.plugin_info, os.path.join(os.path.dirname(__file__), 'info.json'))

        from .logic_base import LogicBase
        from .logic_tv import LogicTv
        from .logic_mv import LogicMv
        from .logic_av import LogicAv

        if use_av: P.module_list = [LogicBase(P), LogicTv(P), LogicMv(P), LogicAv(P)]
        else: P.module_list = [LogicBase(P), LogicTv(P), LogicMv(P)]
        P.logic = Logic(P)
        default_route(P)

    except Exception as e: 
        P.logger.error('Exception:%s', e)
        P.logger.error(traceback.format_exc())

@P.blueprint.route('/api/<sub>', methods=['GET', 'POST'])                                                                         
def baseapi(sub):
    P.logger.debug('API: %s', sub)
    try:
        from .logic_base import LogicBase
        P.logger.debug(request.form)
        if sub == 'scan_completed':
            LogicBase.callback_handler(request.form)
            return 'ok'
        elif sub == 'proxy':
            from .utils import ScmUtil
            return ScmUtil.proxy_handler(request)

    except Exception as e: 
        P.logger.error('Exception:%s', e)
        P.logger.error(traceback.format_exc())

logger = P.logger
initialize()
