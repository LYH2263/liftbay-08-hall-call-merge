import { useEffect, useState } from "react";
import { api } from "../api/client";
type B = { id: number; name: string; floors: number };
type Call = { id: number; building_id: number; floor: number; direction: string; passengers: number; status: string; assigned_car_id: number | null; score: string };
export default function CallsPage() {
  const [buildings, setBuildings] = useState<B[]>([]);
  const [rows, setRows] = useState<Call[]>([]);
  const [bid, setBid] = useState<number | "">("");
  const [floor, setFloor] = useState(5);
  const [dir, setDir] = useState("up");
  const [pax, setPax] = useState(1);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const reload = () => api<Call[]>("/calls").then(r => { setRows(r); setPicked([]); });
  useEffect(() => {
    api<B[]>("/buildings").then(b => { setBuildings(b); if (b[0]) setBid(b[0].id); });
    reload();
  }, []);
  async function create() {
    setErr("");
    try {
      await api("/calls", { method: "POST", body: JSON.stringify({ building_id: bid, floor, direction: dir, passengers: pax }) });
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  const pickedRows = rows.filter(c => picked.includes(c.id));
  const sameGroup = pickedRows.length >= 2 && pickedRows.every(c =>
    c.status === "waiting"
    && c.building_id === pickedRows[0].building_id
    && c.floor === pickedRows[0].floor
    && c.direction === pickedRows[0].direction);
  function toggle(id: number) {
    setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);
  }
  async function merge() {
    setErr("");
    try {
      await api("/calls/merge", { method: "POST", body: JSON.stringify({ call_ids: picked }) });
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); reload(); }
  }
  return (<>
    <h2>呼梯</h2>
    <div className="toolbar">
      <select value={bid} onChange={e => setBid(Number(e.target.value))}>{buildings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select>
      <input type="number" value={floor} onChange={e => setFloor(Number(e.target.value))} style={{ width: 72 }} />
      <select value={dir} onChange={e => setDir(e.target.value)}><option value="up">上行</option><option value="down">下行</option></select>
      <input type="number" value={pax} min={1} onChange={e => setPax(Number(e.target.value))} style={{ width: 64 }} />
      <button onClick={create}>登记呼梯</button>
    </div>
    <div className="toolbar">
      <button onClick={merge} disabled={!sameGroup} style={!sameGroup ? { opacity: .45, cursor: "not-allowed" } : undefined}>合并选中（{picked.length}）</button>
      <span className="hint">仅同楼栋、同楼层、同方向的 waiting 呼梯可合并；容量不足时后端会拒绝且原单不变</span>
    </div>
    {err && <div className="err">{err}</div>}
    <table className="table"><thead><tr><th>ID</th><th>楼层</th><th>方向</th><th>人数</th><th>状态</th><th>轿厢</th><th>评分</th><th>合并</th></tr></thead>
    <tbody>{rows.map(c => <tr key={c.id}><td>{c.id}</td><td className="mono">{c.floor}</td><td>{c.direction}</td><td>{c.passengers}</td><td>{c.status}</td><td>{c.assigned_car_id ?? "—"}</td><td className="mono">{c.score || "—"}</td>
      <td>{c.status === "waiting" && <input type="checkbox" checked={picked.includes(c.id)} onChange={() => toggle(c.id)} />}</td></tr>)}</tbody></table>
  </>);
}
