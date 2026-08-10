import React from 'react';
import { Result, Button } from 'antd';

interface State { hasError: boolean; error: Error | null; }

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode }, State
> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面出错了"
          subTitle={this.state.error?.message}
          extra={<Button type="primary" onClick={() => this.setState({ hasError: false })}>重试</Button>}
        />
      );
    }
    return this.props.children;
  }
}
