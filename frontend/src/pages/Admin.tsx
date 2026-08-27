import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { adminApi } from '@/api/client';
import { decodeJwt, isJwtActive } from '@/utils/jwt';
import { brandTagStyle, status } from '@/theme';
import { getErrorMessage } from '@/utils/error';
import { useAppStore } from '@/store';
import type { AdminUserInfo, LogLevel, SystemLogEntry } from '@/types';

const ADMIN_EMAIL = '1140467720@qq.com';
// 「在线」判定窗口：其他用户无本地 JWT，只能凭后端 last_login_at 粗略近似（无活跃心跳）
const ONLINE_WINDOW_MIN = 15;
const LOG_LEVELS: LogLevel[] = ['debug', 'info', 'warning', 'error', 'critical'];
const LEVEL_TAG: Record<LogLevel, { color: string; text: string }> = {
  debug: { color: 'default', text: 'DEBUG' },
  info: { color: 'blue', text: 'INFO' },
  warning: { color: 'orange', text: 'WARN' },
  error: { color: 'red', text: 'ERROR' },
  critical: { color: 'magenta', text: 'CRITICAL' },
};

export function Admin() {
  const user = useAppStore((s) => s.user);
  const userLoaded = useAppStore((s) => s.userLoaded);
  const isAdmin = user?.email?.toLowerCase() === ADMIN_EMAIL.toLowerCase();

  // M7：getMe 尚未返回时 user 仍为 null，直接判无权限会让管理员刷新页面闪「无权限」
  if (!userLoaded) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        <Spin tip="加载中..." />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div>
        <h2>管理后台</h2>
        <Alert
          type="error"
          showIcon
          message="无权限访问"
          description="该页面仅管理员可见。如需访问请联系系统管理员。"
        />
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <SafetyOutlined /> 管理后台
      </h2>
      <Tabs
        defaultActiveKey="users"
        items={[
          { key: 'users', label: '用户管理', children: <UsersPanel /> },
          { key: 'logs', label: '系统日志', children: <LogsPanel /> },
        ]}
      />
    </div>
  );
}

// ─────────── 用户列表 ───────────

function UsersPanel() {
  const [data, setData] = useState<AdminUserInfo[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminApi.listUsers();
      setData((res.data.data || []) as AdminUserInfo[]);
    } catch (e) {
      message.error(getErrorMessage(e, '加载用户失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);

  const token = localStorage.getItem('token');
  // 复用 jwt.ts 的 base64url 解码（原生 atob 不解码 -/_，payload 含此字符会抛异常 → myId 为 null）
  const myId = token ? decodeJwt(token)?.sub ?? null : null;

  const columns: ColumnsType<AdminUserInfo> = [
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
      render: (email: string, row) => (
        <Space>
          <UserOutlined style={{ color: '#888' }} />
          <span style={{ fontWeight: row.is_admin ? 600 : 400 }}>{email}</span>
          {row.is_admin && <Tag style={brandTagStyle}>管理员</Tag>}
        </Space>
      ),
    },
    {
      title: '注册时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '最后登录',
      dataIndex: 'last_login_at',
      key: 'last_login_at',
      width: 180,
      render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      render: (_, row) => {
        // 当前会话用户：JWT 未过期即在线；其他用户无本地 JWT，按 last_login_at 窗口粗略判定
        let online: boolean;
        let tip: string;
        if (row.id === myId) {
          online = isJwtActive(token);
          tip = online ? '当前会话登录态有效' : '当前会话已过期';
        } else if (row.last_login_at) {
          // 后端 last_login_at 落库为 naive UTC，统一按 UTC 解析再比较，避免本地时区偏差
          const last = dayjs(
            row.last_login_at.includes('T') || row.last_login_at.includes('+')
              ? row.last_login_at
              : row.last_login_at.replace(' ', 'T') + 'Z'
          );
          online = dayjs().diff(last, 'minute') <= ONLINE_WINDOW_MIN;
          tip = online ? `最近 ${ONLINE_WINDOW_MIN} 分钟内登录` : '较久未登录';
        } else {
          online = false;
          tip = '从未登录';
        }
        return (
          <Tooltip title={tip}>
            <Badge status={online ? 'success' : 'default'} text={online ? '在线' : '离线'} />
          </Tooltip>
        );
      },
    },
  ];

  return (
    <Card
      title={`注册用户（${data.length}）`}
      extra={
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading} size="small">刷新</Button>
      }
      size="small"
    >
      <Table<AdminUserInfo>
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        pagination={false}
        size="small"
      />
    </Card>
  );
}

// ─────────── 系统日志 ───────────

interface LogFilter {
  levels: LogLevel[];
  source: string;
  email: string;
  range: [Dayjs, Dayjs] | null;
}

function LogsPanel() {
  const [data, setData] = useState<SystemLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [filter, setFilter] = useState<LogFilter>({ levels: [], source: '', email: '', range: null });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        offset: (page - 1) * pageSize,
        limit: pageSize,
      };
      if (filter.levels.length) params.levels = filter.levels.join(',');
      if (filter.source) params.source = filter.source;
      if (filter.email) params.email = filter.email;
      if (filter.range) {
        params.start = filter.range[0].toISOString();
        params.end = filter.range[1].toISOString();
      }
      const res = await adminApi.listLogs(params);
      const payload = res.data.data as { items: SystemLogEntry[]; total: number };
      setData(payload.items);
      setTotal(payload.total);
    } catch (e) {
      message.error(getErrorMessage(e, '加载日志失败'));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, filter]);

  useEffect(() => { void fetchData(); }, [fetchData]);

  // 筛选变化重置到第 1 页
  useEffect(() => { setPage(1); }, [filter]);

  // 列宽设计：元数据列固定且紧凑，消息列为弹性列（tableLayout fixed 下拿剩余宽度）。
  // 此前消息列无宽度 + 表未设 scroll.x → 固定列合计 878px 超出容器时消息列被挤到 0/66px，
  // 表头（消息）随之不可见。scroll.x 兜底窄窗口：超宽时横向滚动而非塌缩。
  const columns: ColumnsType<SystemLogEntry> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 72,
      render: (lvl: LogLevel) => {
        const m = LEVEL_TAG[lvl] || { color: 'default', text: lvl };
        return <Tag color={m.color}>{m.text}</Tag>;
      },
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 170,
      ellipsis: true,
    },
    {
      title: '用户',
      dataIndex: 'email',
      key: 'email',
      width: 150,
      ellipsis: true,
      render: (v: string | null) => v || <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '路径 / 状态',
      key: 'path',
      width: 190,
      ellipsis: true,
      render: (_, row) => row.path ? (
        <Space size={4}>
          {row.method && <Tag>{row.method}</Tag>}
          <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{row.path}</span>
          {row.status_code != null && (
            <Tag color={row.status_code >= 500 ? 'red' : row.status_code >= 400 ? 'orange' : 'green'}>
              {row.status_code}
            </Tag>
          )}
        </Space>
      ) : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      // 弹性列：不设 width、去 ellipsis，长消息自动换行显示完整；stack_trace 走展开行
      render: (msg: string) => <div style={{ wordBreak: 'break-word' }}>{msg}</div>,
    },
  ];

  return (
    <Card
      size="small"
      title={`系统日志（共 ${total} 条）`}
      extra={
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading} size="small">刷新</Button>
      }
    >
      <Form
        layout="inline"
        size="small"
        style={{ marginBottom: 16, flexWrap: 'wrap', gap: 8 }}
      >
        <Form.Item label="级别">
          <Select<LogLevel[]>
            mode="multiple"
            allowClear
            style={{ minWidth: 200 }}
            placeholder="全部"
            value={filter.levels}
            onChange={(v) => setFilter({ ...filter, levels: v })}
            options={LOG_LEVELS.map((l) => ({ value: l, label: LEVEL_TAG[l].text }))}
          />
        </Form.Item>
        <Form.Item label="来源">
          <Input
            allowClear
            placeholder="如 backend.api.chat"
            value={filter.source}
            onChange={(e) => setFilter({ ...filter, source: e.target.value })}
            style={{ width: 200 }}
          />
        </Form.Item>
        <Form.Item label="用户邮箱">
          <Input
            allowClear
            placeholder="模糊匹配"
            value={filter.email}
            onChange={(e) => setFilter({ ...filter, email: e.target.value })}
            style={{ width: 180 }}
          />
        </Form.Item>
        <Form.Item label="时间">
          <DatePicker.RangePicker
            showTime
            value={filter.range}
            onChange={(v) => setFilter({ ...filter, range: v as [Dayjs, Dayjs] | null })}
          />
        </Form.Item>
        <Form.Item>
          <Button
            onClick={() => setFilter({ levels: [], source: '', email: '', range: null })}
          >重置</Button>
        </Form.Item>
      </Form>

      <Table<SystemLogEntry>
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        size="small"
        scroll={{ x: 950 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: ['20', '50', '100'],
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
        expandable={{
          expandedRowRender: (row) => (
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="完整消息">{row.message}</Descriptions.Item>
              {row.stack_trace && (
                <Descriptions.Item label="Stack Trace">
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12, color: status.error }}>
                    {row.stack_trace}
                  </pre>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="元数据">
                {`id=${row.id} | user_id=${row.user_id || '-'} | created_at=${row.created_at}`}
              </Descriptions.Item>
            </Descriptions>
          ),
        }}
      />
    </Card>
  );
}
