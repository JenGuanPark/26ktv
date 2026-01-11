import { useEffect, useState } from 'react';
import axios from 'axios';
import { Layout, Card, Table, Tabs, Statistic, Row, Col, Tag, Spin, DatePicker, List, Avatar } from 'antd';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';

// 设置 dayjs 本地化
dayjs.locale('zh-cn');

const { Header, Content } = Layout;

const API_URL = 'https://two6ktv.onrender.com';

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#AF19FF', '#FF1919'];
const CATEGORY_COLORS = {
  CNY: {
    '餐饮': '#1677ff',
    '交通': '#13c2c2',
    '购物': '#52c41a',
    '居住': '#722ed1',
    '娱乐': '#eb2f96',
    '医疗': '#fa8c16',
    '转账': '#f5222d',
    '其他': '#595959',
  },
  HKD: {
    '餐饮': '#fa8c16',
    '交通': '#b37feb',
    '购物': '#fadb14',
    '居住': '#2f54eb',
    '娱乐': '#13c2c2',
    '医疗': '#73d13d',
    '转账': '#d4380d',
    '其他': '#595959',
  },
  USDT: {
    '餐饮': '#1677ff',
    '交通': '#13c2c2',
    '购物': '#52c41a',
    '居住': '#722ed1',
    '娱乐': '#eb2f96',
    '医疗': '#fa8c16',
    '转账': '#f5222d',
    '其他': '#595959',
  }
};

function App() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeCurrency, setActiveCurrency] = useState('CNY');
  const [selectedMonth, setSelectedMonth] = useState(dayjs());
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < 768 : false);

  const deriveCategory = (record) => {
    const base = (record?.category || '').trim();
    if (base && base !== '其他') return base;
    const src = `${record?.item || ''} ${record?.raw_text || ''}`.toLowerCase();
    const hasAny = (arr) => arr.some(k => src.includes(k));
    if (hasAny(['转账', 'fps', '轉帳', '轉賬', '转數快'])) return '转账';
    if (hasAny(['餐', '饭', '午饭', '晚饭', '早餐', '吃饭', '超市', '买菜', '咖啡', '奶茶', '星巴克', '麦当劳', 'mcdonald', 'kfc'])) return '餐饮';
    if (hasAny(['打车', '出租', '地铁', '公交', '的士', '巴士', 'mtr', '滴滴', '停车', '加油'])) return '交通';
    if (hasAny(['快递', '顺丰', '菜鸟', '淘宝', '京东', '购物', '买衣服', '买鞋'])) return '购物';
    if (hasAny(['房租', '水费', '电费', '燃气', '物业'])) return '居住';
    if (hasAny(['电影', '游戏', '旅游', 'ktv'])) return '娱乐';
    if (hasAny(['医院', '药', '体检', '看病'])) return '医疗';
    return base || '其他';
  };

  useEffect(() => {
    fetchData();
    // Simple polling to refresh data every 10 seconds
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const fetchData = async () => {
    try {
      console.log("Starting fetch from:", API_URL);
      setError(null);
      
      // Add timeout to force error if backend hangs
      const res = await axios.get(`${API_URL}/transactions/`, { timeout: 15000 });
      
      console.log("Fetch success:", res.data);
      setTransactions(res.data || []);
    } catch (error) {
      console.error("Failed to fetch data", error);
      let msg = error.message;
      if (error.code === 'ECONNABORTED') {
        msg = "Connection timed out. Backend is sleeping or unreachable.";
      } else if (error.response) {
        msg = `Server Error: ${error.response.status} ${JSON.stringify(error.response.data)}`;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm("⚠️ 警告：确定要删除所有账单数据吗？\n\n此操作不可恢复！")) return;
    
    // Double confirmation
    if (!window.confirm("再次确认：真的要清空所有数据吗？")) return;

    try {
      setLoading(true);
      await axios.delete(`${API_URL}/transactions/reset`);
      alert("✅ 所有数据已成功清空");
      fetchData();
    } catch (error) {
      console.error("Reset failed", error);
      alert("❌ 删除失败: " + (error.response?.data?.detail || error.message));
      setLoading(false);
    }
  };

  if (loading && transactions.length === 0) return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', flexDirection: 'column', gap: 20 }}>
      <Spin size="large" />
      <div>Connecting to Backend... (First load may take 1 min)</div>
    </div>
  );

  if (error && transactions.length === 0) return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', flexDirection: 'column', gap: 20 }}>
      <Tag color="red" style={{ fontSize: 16, padding: 10 }}>Error: {error}</Tag>
      <div>Backend URL: {API_URL}</div>
      <div onClick={() => window.location.reload()} style={{ cursor: 'pointer', color: '#1677ff' }}>Click to Retry</div>
    </div>
  );

  // 1. 先按币种过滤
  const currencyData = transactions.filter(t => t.currency === activeCurrency);

  // 2. 再按月份过滤
  const currentData = currencyData.filter(t => 
    dayjs(t.created_at).isSame(selectedMonth, 'month')
  );
  
  // Calculate total
  const totalAmount = currentData.reduce((sum, t) => sum + t.amount, 0);
  
  // Calculate category stats for Pie Chart
  const categoryStats = currentData.reduce((acc, t) => {
    const cat = deriveCategory(t);
    acc[cat] = (acc[cat] || 0) + t.amount;
    return acc;
  }, {});
  
  const pieData = Object.keys(categoryStats).map(key => ({
    name: key,
    value: categoryStats[key]
  }));

  // Calculate member stats
  const memberStats = currentData.reduce((acc, t) => {
    const user = t.user_name || 'Unknown';
    acc[user] = (acc[user] || 0) + t.amount;
    return acc;
  }, {});

  const memberData = Object.keys(memberStats)
    .map(key => ({
      name: key,
      value: memberStats[key]
    }))
    .sort((a, b) => b.value - a.value); // 降序排列

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (text) => dayjs(text).format('YYYY-MM-DD HH:mm'),
      sorter: (a, b) => new Date(a.created_at) - new Date(b.created_at),
      width: 180,
    },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      render: (_, record) => <Tag color="blue">{deriveCategory(record)}</Tag>,
      width: 100,
    },
    {
      title: '项目',
      dataIndex: 'item',
      key: 'item',
      ellipsis: true,
      width: 240,
    },
    {
      title: '金额',
      dataIndex: 'amount',
      key: 'amount',
      render: (amount) => <span className="font-bold text-lg">{amount.toFixed(2)}</span>,
      sorter: (a, b) => a.amount - b.amount,
      width: 120,
    },
    {
      title: '记账人',
      dataIndex: 'user_name',
      key: 'user_name',
      render: (text) => <Tag color="orange">{text || 'Unknown'}</Tag>,
      width: 120,
    },
  ];

  const items = [
    {
      key: 'CNY',
      label: '🇨🇳 人民币 (CNY)',
      children: renderContent(currentData, totalAmount, pieData, memberData, columns, activeCurrency, isMobile),
    },
    {
      key: 'HKD',
      label: '🇭🇰 港币 (HKD)',
      children: renderContent(currentData, totalAmount, pieData, memberData, columns, activeCurrency, isMobile),
    },
    {
      key: 'USDT',
      label: '🇺🇸 泰达币 (USDT)',
      children: renderContent(currentData, totalAmount, pieData, memberData, columns, activeCurrency, isMobile),
    },
  ];

  const headerClass = isMobile
    ? "bg-white shadow-sm flex items-center justify-between px-4 py-3 sticky top-0 z-10"
    : "bg-white shadow-sm flex items-center justify-between px-6 sticky top-0 z-10";

  return (
    <Layout className="min-h-screen bg-gray-50">
      <Header className={headerClass} style={{ height: 'auto', lineHeight: 'normal' }}>
        <h1 className={`${isMobile ? 'text-lg' : 'text-xl'} font-bold text-gray-800 m-0`}>
          📊 {isMobile ? '家庭记账' : '家庭双币记账本'}
        </h1>
        <div className="flex items-center gap-2">
          {!isMobile && <span className="text-gray-500">选择月份:</span>}
          <DatePicker 
            picker="month" 
            value={selectedMonth} 
            onChange={setSelectedMonth}
            allowClear={false}
            format={isMobile ? "YYYY-MM" : "YYYY年 MM月"}
            style={{ width: isMobile ? 110 : 140 }}
            inputReadOnly
          />
        </div>
      </Header>
      <Content className="p-6 max-w-7xl mx-auto w-full">
        {loading && transactions.length === 0 ? (
          <div className="flex justify-center items-center h-64">
            <Spin size="large" />
          </div>
        ) : (
          <Tabs 
            defaultActiveKey="CNY" 
            activeKey={activeCurrency}
            onChange={setActiveCurrency}
            items={items} 
            type="card"
            size="large"
            destroyInactiveTabPane={true} // 确保切换Tab时彻底重绘
          />
        )}

        {/* Reset Data Button - Disabled by user request */}
        {/* {!loading && (
          <div className="mt-12 mb-6 text-center">
            <div className="text-gray-400 text-sm mb-2">数据管理</div>
            <button 
              onClick={handleReset}
              className="px-4 py-2 text-red-500 border border-red-200 rounded hover:bg-red-50 hover:border-red-300 transition-colors text-sm"
            >
              🗑️ 清空所有账单数据
            </button>
          </div>
        )} */}
      </Content>
    </Layout>
  );
}

function renderContent(data, totalAmount, pieData, memberData, columns, currency, isMobile) {
  const currencySymbol = currency === 'CNY' ? '¥' : (currency === 'HKD' ? 'HK$' : '₮');
  const colorMap = CATEGORY_COLORS[currency] || CATEGORY_COLORS.CNY;

  return (
    <div className={isMobile ? "space-y-4" : "space-y-6"}>
      {/* 顶部统计卡片 */}
      <Row gutter={[16, 16]}>
        <Col span={24} md={8}>
          <Card hoverable className={isMobile ? "h-full flex flex-col justify-center bg-blue-50 border-blue-100" : "h-full flex flex-col justify-center bg-blue-50 border-blue-100"} bodyStyle={isMobile ? { padding: '12px 16px' } : {}}>
            <Statistic 
              title="本月总支出" 
              value={totalAmount} 
              precision={2} 
              prefix={currencySymbol}
              valueStyle={{ color: '#1677ff', fontWeight: 'bold' }}
            />
            <div className="text-gray-400 text-xs mt-2">
              {data.length} 笔交易
            </div>
          </Card>
        </Col>
        
        {/* 成员支出排行 */}
        <Col span={24} md={16}>
          <Card title="👨‍👩‍👧‍👦 成员支出排行" className="h-full" bodyStyle={isMobile ? { padding: '8px 16px' } : { padding: '10px 24px' }}>
            {memberData.length > 0 ? (
              <List
                itemLayout="horizontal"
                dataSource={memberData}
                renderItem={(item, index) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={<Avatar style={{ backgroundColor: COLORS[index % COLORS.length] }}>{item.name[0]}</Avatar>}
                      title={item.name}
                      description={<div className="w-full bg-gray-100 h-2 rounded-full mt-1 overflow-hidden">
                        <div 
                          className="h-full rounded-full" 
                          style={{ 
                            width: `${(item.value / totalAmount) * 100}%`,
                            backgroundColor: COLORS[index % COLORS.length]
                          }} 
                        />
                      </div>}
                    />
                    <div className="font-bold text-lg">
                      {currencySymbol} {item.value.toFixed(2)}
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <div className="text-gray-400 py-8 text-center">本月暂无数据</div>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {/* 分类饼图 */}
        <Col span={24} md={12}>
           <Card title="📊 支出类别分布">
             <div className={isMobile ? "h-56" : "h-72"}>
               {pieData.length > 0 ? (
                 <ResponsiveContainer width="100%" height="100%">
                   <PieChart>
                     <Pie
                       data={pieData}
                       cx="50%"
                       cy="50%"
                       innerRadius={isMobile ? 50 : 60}
                       outerRadius={isMobile ? 70 : 80}
                       paddingAngle={5}
                       dataKey="value"
                     >
                       {pieData.map((entry, index) => {
                         const fill = colorMap[entry.name] || COLORS[index % COLORS.length];
                         return <Cell key={`cell-${index}`} fill={fill} />;
                       })}
                     </Pie>
                     <Tooltip formatter={(value) => `${currencySymbol} ${value.toFixed(2)}`} />
                     <Legend verticalAlign="bottom" height={36}/>
                   </PieChart>
                 </ResponsiveContainer>
               ) : (
                 <div className="flex items-center justify-center h-full text-gray-400">
                   暂无数据
                 </div>
               )}
             </div>
           </Card>
        </Col>

        {/* 最近支出记录 */}
        <Col span={24} md={12}>
           <Card title="📅 最近支出记录" className="h-full">
             <Table 
                dataSource={data.slice(0, 5)} 
                columns={columns}
                rowKey="id" 
                pagination={false}
                size="small"
                sticky
                scroll={{ x: 'max-content' }}
             />
             <div className="mt-4 text-center">
                <span className="text-gray-400 text-sm">显示最近5笔，查看下方完整列表</span>
             </div>
           </Card>
        </Col>
      </Row>

      <Card title="📜 完整收支明细" className="shadow-sm">
        <Table 
          dataSource={data} 
          columns={columns} 
          rowKey="id" 
          pagination={{ pageSize: isMobile ? 5 : 10, simple: isMobile, showTotal: (total) => `共 ${total} 条` }}
          size={isMobile ? 'small' : 'middle'}
          tableLayout="fixed"
          sticky
          scroll={{ x: 'max-content' }}
        />
      </Card>
    </div>
  );
}

export default App;
