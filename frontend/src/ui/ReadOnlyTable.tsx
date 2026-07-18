import { Input, Select, Table } from "antd";
import type { TableProps } from "antd";
import { useMemo, useState } from "react";
import EmptyState from "./EmptyState";

interface FilterOption {
  label: string;
  value: string;
}

export interface RemotePagination {
  current: number;
  pageSize: number;
  total: number;
  onChange: (page: number, pageSize: number) => void;
}

interface ReadOnlyTableProps<T extends object> {
  columns: TableProps<T>["columns"];
  data: readonly T[];
  rowKey: TableProps<T>["rowKey"];
  searchPlaceholder?: string;
  filterOptions?: readonly FilterOption[];
  getFilterValue?: (record: T) => string;
  pageSize?: number;
  remotePagination?: RemotePagination;
  showSearch?: boolean;
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
  remotePagination,
  showSearch = true,
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
  const pagination: TableProps<T>["pagination"] = remotePagination
    ? {
      current: remotePagination.current,
      pageSize: remotePagination.pageSize,
      total: remotePagination.total,
      showSizeChanger: true,
      showQuickJumper: false,
      showTotal: (total) => `共 ${total} 条`,
      onChange: (page, nextPageSize) => remotePagination.onChange(page, nextPageSize),
    }
    : {
      pageSize,
      showSizeChanger: true,
      showQuickJumper: false,
      showTotal: (total) => `共 ${total} 条`,
    };

  return (
    <div className="readonly-table">
      {showSearch || (filterOptions.length > 0 && getFilterValue) ? (
        <div className="readonly-table__toolbar">
          {showSearch ? (
            <Input
              allowClear
              aria-label="筛选表格"
              placeholder={searchPlaceholder}
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
            />
          ) : null}
          {filterOptions.length && getFilterValue ? (
            <Select
              aria-label="按状态筛选"
              value={filterValue}
              onChange={setFilterValue}
              options={[{ label: "全部状态", value: "all" }, ...filterOptions]}
            />
          ) : null}
        </div>
      ) : null}
      <Table<T>
        className="readonly-table__table"
        columns={columns}
        dataSource={filteredData}
        rowKey={rowKey}
        scroll={{ x: "max-content" }}
        locale={{ emptyText: <EmptyState description={emptyDescription} /> }}
        pagination={pagination}
      />
    </div>
  );
}
