import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <section className="page-frame">
      <header className="page-header">
        <div>
          <h1>页面不存在</h1>
          <p>当前地址不在量化运营台的已注册路由中。</p>
        </div>
      </header>
      <section className="panel">
        <div className="panel__body">
          <p className="soft-note warning-note">请返回运行总览继续查看只读运营信息。</p>
          <Link className="data-link" to="/">
            返回运行总览
          </Link>
        </div>
      </section>
    </section>
  );
}
