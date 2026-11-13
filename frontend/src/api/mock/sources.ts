// mock 样例出处：逐字取自 backend/data/来源登记表-样例.csv 的 5 行，
// 并以契约生成类型 components['schemas']['SourceOut'] 实例化（简报 S6：不自由发挥）。
// 九列值与 CSV 一致；domain/sections 在样例 CSV 中不存在 → 省略；
// verified 依据 license_note 的核验描述：官网直连核验过的文章为 true，电子版待采集的电子书为 false。
import type { components } from '../types'

type SourceOut = components['schemas']['SourceOut']

export const SAMPLE_SOURCES: SourceOut[] = [
  {
    source_id: 'S001',
    title: '湖南郴州建成红军长征档案数据库',
    publisher: '中国档案报',
    publish_date: '2026-10-19',
    url_or_path: 'http://www.zgdazxw.com.cn/2026-10/19/content_505878.html',
    access_date: '2026-11-13',
    license_note:
      '官网公开文章。原载《中国档案报》2026年10月19日 总第4506期 第二版；作者苏莉 李慕梅；2026-11-13 直连打开核验，正文数字（归集长征档案2123件）与《数据来源清单.md》第16项一致',
    corpus_tier: '核心',
    media_type: '文章',
    verified: true,
  },
  {
    source_id: 'S002',
    title: '红军长征记',
    publisher: '解放军出版社',
    publish_date: '2026',
    url_or_path: 'https://www.dswxyjy.org.cn/n1/2026/1015/c434085-40815320.html',
    access_date: '2026-11-13',
    license_note:
      '公开出版物（2026年修订再版，在2006年版基础上校订并增注释；1942年11月成书为党内参考资料）。电子版文件待采集，本列先填出版信息核验页；仅校内研究与教学使用，系统只展示逐字引文片段与出处',
    corpus_tier: '核心',
    media_type: '电子书',
    verified: false,
  },
  {
    source_id: 'S003',
    title: '中国共产党历史（第三卷上册）',
    publisher: '中共党史出版社',
    publish_date: '2024',
    url_or_path: 'https://www.dswxyjy.org.cn/n1/2024/1223/c423712-40387397.html',
    access_date: '2026-11-13',
    license_note:
      '公开出版物。经党中央批准由中央党史和文献研究院编写，2024年12月出版发行，记述1978年12月—1989年6月党史，约42万字；电子版文件待采集，本列先填出版信息核验页',
    corpus_tier: '核心',
    media_type: '电子书',
    verified: false,
  },
  {
    source_id: 'S004',
    title: '万里征途入诗行',
    publisher: '中国共产党新闻网',
    publish_date: '2026-11-12',
    url_or_path: 'http://cpc.people.com.cn/n1/2026/1112/c443712-40832512.html',
    access_date: '2026-11-13',
    license_note:
      '官网公开文章。原载《解放军报》2026年11月12日，作者朱延涛 张亚琼，载于人民网·中国共产党新闻网党史频道；2026-11-13 直连打开核验',
    corpus_tier: '补充',
    media_type: '文章',
    verified: true,
  },
  {
    source_id: 'S005',
    title: '长沙现存最早的地方志——明·嘉靖《长沙府志》',
    publisher: '中国方志网',
    publish_date: '2025-04-25',
    url_or_path: 'https://www.difangzhi.cn/zs/zsxj/202504/t20250425_5870859.shtml',
    access_date: '2026-11-13',
    license_note:
      '官网公开文章（来源标注为「方志长沙」微信公众号，经中国方志网整篇刊发，故以中国方志网为发布机构）。页内记载点校版2017年9月由湖南师范大学出版社出版、29.7万字，可作该地方志整理本的出版依据',
    corpus_tier: '补充',
    media_type: '文章',
    verified: true,
  },
]
