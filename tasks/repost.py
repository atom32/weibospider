# -*-coding:utf-8 -*-
from db import wb_data
from db import weibo_repost
from tasks.workers import app
from page_parse import repost
from logger.log import crawler
from db.redis_db import IdNames
from page_get.basic import get_page
from page_get import user as user_get
from config.conf import get_max_repost_page


base_url = 'http://weibo.com/aj/v6/mblog/info/big?ajwvr=6&id={}&page={}'


@app.task
def crawl_repost_by_page(mid, page_num):
    cur_url = base_url.format(mid, page_num)
    html = get_page(cur_url, user_verify=False)
    repost_datas = repost.get_repost_list(html, mid)
    if page_num == 1:
        wb_data.set_weibo_repost_crawled(mid)
    return html, repost_datas


@app.task(ignore_result=True)
def crawl_repost_page(mid, uid):
    limit = get_max_repost_page() + 1
    first_repost_data = crawl_repost_by_page(mid, 1)
    total_page = repost.get_total_page(first_repost_data[0])
    repost_datas = first_repost_data[1]

    if not repost_datas:
        return

    root_user = user_get.get_profile(uid)

    if total_page < limit:
        limit = total_page + 1
    for page_num in range(2, limit):
        # app.send_task('tasks.comment.crawl_comment_by_page', args=(mid, page_num), queue='comment_page_crawler',
        #               routing_key='comment_page_info')
        cur_repost_datas = crawl_repost_by_page(mid, page_num)[1]
        if cur_repost_datas:
            repost_datas.extend(cur_repost_datas)

    # 补上user_id，方便可视化
    for index, repost_obj in enumerate(repost_datas):
        user_id = IdNames.fetch_uid_by_name(repost_obj.parent_user_name)
        if not user_id:
            # 设置成根用户的uid和用户名
            repost_obj.parent_user_id = root_user.uid
            repost_obj.parent_user_name = root_user.name
        else:
            repost_obj.parent_user_id = user_id
        repost_datas[index] = repost_obj

    weibo_repost.save_reposts(repost_datas)


@app.task(ignore_result=True)
def excute_repost_task():
    # 以当前微博为源微博进行分析，不向上溯源，如果有同学需要向上溯源，需要自己判断一下该微博是否是根微博
    weibo_datas = wb_data.get_weibo_repost_not_crawled()
    crawler.info('本次一共有{}条微博需要抓取转发信息'.format(len(weibo_datas)))

    for weibo_data in weibo_datas:
        app.send_task('tasks.repost.crawl_repost_page', args=(weibo_data.weibo_id, weibo_data.uid),
                      queue='repost_crawler', routing_key='repost_info')
