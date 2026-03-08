import { useState } from "react";
import axios from "axios";

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

      const res = await axios.post(
        "http://localhost:5001/upload_orders",
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data"
          }
        }
      );

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

    <div>

      <h2>Upload Orders Excel</h2>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files[0] || null)}
      />

      <br /><br />

      <button onClick={uploadFile} disabled={loading}>
        {loading ? "Uploading..." : "Upload Orders"}
      </button>


      {/* Show conflicts if any */}

      {conflicts.length > 0 && (

        <div style={{ marginTop: 30 }}>

          <h3>Possible Duplicate Orders</h3>

          <table border="1" cellPadding="6">

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