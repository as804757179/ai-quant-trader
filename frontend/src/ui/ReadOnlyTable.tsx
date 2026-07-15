import { Input, Select, Table } from "antd";
import type { TableProps } from "antd";
import { useMemo, useState } from "react";
import EmptyState from "./EmptyState";

interface FilterOption {
  label: string;
  value: string;
}

interface ReadOnlyTableProps<T extends object> {
  columns: TableProps<T>["columns"];
  data: readonly T[];
  rowKey: TableProps<T>["rowKey"];
  searchPlaceholder?: string;
  filterOptions?: readonly FilterOption[];
  getFilterValue?: (record: T) => string;
  pageSize?: number;
  emptyDescription?: string;
}

export default function ReadOnlyTable<T extends object>({
  columns,
  data,
  rowKey,
  searchPlaceholder = "筛选代码、ID 或原因",
  filterOptions = [],
  getFilterValue,
  pageSize = 10,
  emptyDescription = "待接入",
}: ReadOnlyTableProps<T>) {
  const [keyword, setKeyword] = useState("");
  const [filterValue, setFilterValue] = useState("all");
  const filteredData = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLocaleLowerCase("zh-CN");

    return data.filter((record) => {
      const matchesKeyword =
        !normalizedKeyword || JSON.stringify(record).toLocaleLowerCase("zh-CN").includes(normalizedKeyword);
      const matchesFilter =
        filterValue === "all" || !getFilterValue || getFilterValue(record) === filterValue;

      return matchesKeyword && matchesFilter;
    });
  }, [data, filterValue, getFilterValue, keyword]);

  return (
    <div className="readonly-table">
      <div className="readonly-table__toolbar">
        <Input
          allowClear
          aria-label="筛选表格"
          placeholder={searchPlaceholder}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
        {filterOptions.length && getFilterValue ? (
          <Select
            aria-label="按状态筛选"
            value={filterValue}
            onChange={setFilterValue}
            options={[{ label: "全部状态", value: "all" }, ...filterOptions]}
          />
        ) : null}
      </div>
      <Table<T>
        className="readonly-table__table"
        columns={columns}
        dataSource={filteredData}
        rowKey={rowKey}
        scroll={{ x: "max-content" }}
        locale={{ emptyText: <EmptyState description={emptyDescription} /> }}
        pagination={{
          pageSize,
          showSizeChanger: true,
          showQuickJumper: false,
          showTotal: (total) => `共 ${total} 条`,
        }}
      />
    </div>
  );
}
