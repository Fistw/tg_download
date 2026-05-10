import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Downloads from './pages/Downloads';
import Uploads from './pages/Uploads';
import Dedupe from './pages/Dedupe';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="downloads" element={<Downloads />} />
          <Route path="uploads" element={<Uploads />} />
          <Route path="dedupe" element={<Dedupe />} />
        </Route>
        <Route path="/dashboard" element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="downloads" element={<Downloads />} />
          <Route path="uploads" element={<Uploads />} />
          <Route path="dedupe" element={<Dedupe />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
