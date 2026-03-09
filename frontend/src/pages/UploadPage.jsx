import { useState } from "react";
import { uploadOrders } from "../api";

function UploadPage() {

  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [conflicts, setConflicts] = useState([]);

  const uploadFile = async () => {

    if (!file) {
      alert("Please choose a file first");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {

      setLoading(true);
      setConflicts([]);

      const res = await uploadOrders(formData);

      alert(
        `Orders Loaded: ${res.data.rows_inserted}\nConflicts: ${res.data.conflicts}`
      );

      if (res.data.conflict_rows) {
        setConflicts(res.data.conflict_rows);
      }

    } catch (err) {

      console.error(err);

      const msg =
        err?.response?.data?.message ||
        err?.response?.data?.error ||
        err?.message ||
        "Upload failed";

      alert(msg);

    } finally {

      setLoading(false);

    }

  };

  return (

    <div className="page">

      <h1>Upload Orders</h1>

      <div className="card">

        <input
          type="file"
          onChange={(e) => setFile(e.target.files[0] || null)}
        />

        <br /><br />

        <button
          className="primary-btn"
          onClick={uploadFile}
          disabled={loading}
        >
          {loading ? "Uploading..." : "Upload Orders"}
        </button>

      </div>

      {conflicts.length > 0 && (

        <div className="card">

          <h3>Possible Duplicate Orders</h3>

          <table className="table">

            <thead>
              <tr>
                <th>Name</th>
                <th>Weight</th>
                <th>Service</th>
                <th>Date</th>
              </tr>
            </thead>

            <tbody>

              {conflicts.map((row, i) => (

                <tr key={i}>
                  <td>{row.name}</td>
                  <td>{row.weight}</td>
                  <td>{row.service}</td>
                  <td>{row.date}</td>
                </tr>

              ))}

            </tbody>

          </table>

        </div>

      )}

    </div>

  );
}

export default UploadPage;