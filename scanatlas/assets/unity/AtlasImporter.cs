// Atlas Unity Importer
// Installed at Assets/Atlas/Editor/AtlasImporter.cs. No external packages required.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

[InitializeOnLoad]
public static class AtlasImporter
{
    [Serializable] public class InputFile { public string path; public string role; }
    [Serializable] public class MaterialBinding { public string material; public string texture_set; }
    [Serializable] public class Request
    {
        public string job_id, asset_id, name, kind, quality, asset_folder, rig;
        public InputFile[] files;
        public MaterialBinding[] material_bindings;
    }
    [Serializable] public class Report
    {
        public string job_id, status, asset_folder, error, pipeline;
        public float progress_percent;
        public bool progress_estimated = true;
        public string stage;
        public List<string> prefabs = new List<string>();
        public List<string> materials = new List<string>();
        public List<string> animations = new List<string>();
        public List<string> textures = new List<string>();
        public List<string> warnings = new List<string>();
    }
    sealed class Map { public string Path, Role, Key; public int Priority; }
    sealed class MaterialSet { public string Key; public Material Material; }
    sealed class Pixels
    {
        public int Width, Height;
        public Color32[] Values;
        public Color32 At(int x, int y, int width, int height)
        {
            return Values[Math.Min(Height - 1, (int)((long)y * Height / height)) * Width
                + Math.Min(Width - 1, (int)((long)x * Width / width))];
        }
    }

    static bool busy;
    static double nextPoll;
    const int MaxPackedSize = 4096;
    static readonly Regex SafeId = new Regex(@"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$");
    static readonly string[] TextureExtensions = { ".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp", ".exr", ".hdr", ".psd" };
    static readonly Regex MapWords = new Regex(@"(?i)(base[ _-]?colou?r|albedo|diffuse|diff|normal(?:[ _-]?(?:opengl|directx|gl|dx))?|roughness|rough|smoothness|smooth|glossiness|gloss|metallic|metalness|metal|specular|ambient[ _-]?occlusion|occlusion|opacity|alpha|emissive|emission|displacement|height|bump|(?:^|[ _-])(?:ao|colou?r|disp|(?:nor|nrm)(?:[ _-]?(?:opengl|directx|gl|dx))?)(?=$|[ _-]))");

    static AtlasImporter() { EditorApplication.update += Update; }
    static void Update()
    {
        if (EditorApplication.timeSinceStartup < nextPoll) return;
        nextPoll = EditorApplication.timeSinceStartup + 1;
        ProcessPending();
    }

    // Also callable with Unity -executeMethod AtlasImporter.ProcessPending.
    public static void ProcessPending()
    {
        if (busy || EditorApplication.isCompiling || EditorApplication.isUpdating || EditorApplication.isPlayingOrWillChangePlaymode) return;
        busy = true;
        try
        {
            string root = ProjectRoot;
            string queue = Path.Combine(root, "AtlasImports", "requests");
            if (!Directory.Exists(queue)) return;
            RejectLinks(queue, root);
            foreach (string file in Directory.GetFiles(queue, "*.json").OrderBy(p => p, StringComparer.Ordinal))
            {
                string id = Path.GetFileNameWithoutExtension(file);
                if (!SafeId.IsMatch(id)) continue;
                string reportPath = Path.Combine(root, "AtlasImports", "reports", id + ".json");
                RejectLinks(reportPath, root);
                if (File.Exists(reportPath))
                {
                    try
                    {
                        var previous = JsonUtility.FromJson<Report>(File.ReadAllText(reportPath));
                        if (previous != null && (previous.status == "complete" || previous.status == "failed")) continue;
                    }
                    catch { /* A interrupted write or corrupt report can be retried. */ }
                }
                var report = new Report { job_id = id, status = "processing", pipeline = Pipeline() };
                try
                {
                    Progress(report, 5, "Validating");
                    RejectLinks(file, root);
                    if (new FileInfo(file).Length > 8 * 1024 * 1024) throw new InvalidDataException("Import request exceeds 8 MiB.");
                    var request = JsonUtility.FromJson<Request>(File.ReadAllText(file));
                    Validate(request, id);
                    report.asset_folder = request.asset_folder;
                    WriteReport(reportPath, report);
                    Import(request, report);
                    Progress(report, 95, "Saving assets");
                    AssetDatabase.SaveAssets();
                    report.status = "complete";
                    report.progress_percent = 100;
                    report.stage = "Complete";
                }
                catch (Exception exception)
                {
                    report.status = "failed";
                    report.stage = "Failed";
                    report.error = exception.GetBaseException().Message;
                    Debug.LogError("Atlas import " + id + ": " + report.error);
                }
                WriteReport(reportPath, report);
            }
        }
        catch (Exception exception) { Debug.LogError("Atlas importer: " + exception.Message); }
        finally { busy = false; }
    }

    static string ProjectRoot { get { return Path.GetFullPath(Path.Combine(Application.dataPath, "..")); } }
    static void Validate(Request request, string id)
    {
        if (request == null || request.job_id != id || string.IsNullOrEmpty(request.asset_id) || request.asset_id.Length > 512 || request.asset_id.Any(char.IsControl))
            throw new InvalidDataException("Invalid job or asset identifier.");
        string safeAssetId = Regex.Replace(request.asset_id, @"[^A-Za-z0-9_-]", "_");
        safeAssetId = safeAssetId.Substring(0, Math.Min(100, safeAssetId.Length));
        string expected = "Assets/Atlas/Imported/" + safeAssetId + "/" + id;
        if (request.asset_folder != expected) throw new InvalidDataException("Asset folder must be " + expected + ".");
        if (request.rig != null && request.rig != "" && request.rig != "auto" && request.rig != "generic" && request.rig != "humanoid" && request.rig != "none")
            throw new InvalidDataException("Rig must be auto, generic, humanoid, or none.");
        if (request.files == null || request.files.Length == 0 || request.files.Length > 10000)
            throw new InvalidDataException("Request must contain 1 to 10000 files.");
        RejectLinks(Absolute(request.asset_folder), ProjectRoot);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (InputFile file in request.files)
        {
            if (file == null || string.IsNullOrWhiteSpace(file.path) || file.path.Contains('\\') || file.path.Contains(':')
                || Path.IsPathRooted(file.path) || file.path.Split('/').Any(p => p == ".." || p == "." || p == ""))
                throw new InvalidDataException("Unsafe file path in request.");
            if (!seen.Add(file.path)) throw new InvalidDataException("Duplicate file path: " + file.path);
            string extension = Path.GetExtension(file.path).ToLowerInvariant();
            if (!TextureExtensions.Contains(extension) && extension != ".fbx" && extension != ".obj" && extension != ".mtl")
                throw new InvalidDataException("Unsupported file type: " + extension + ". Only textures, FBX, OBJ and MTL are accepted.");
            string absolute = Absolute(request.asset_folder + "/" + file.path);
            RejectLinks(absolute, ProjectRoot);
            if (!File.Exists(absolute)) throw new FileNotFoundException("Transferred asset is missing: " + file.path);
        }
    }

    static string Absolute(string path)
    {
        string root = ProjectRoot;
        string absolute = Path.GetFullPath(Path.Combine(root, path));
        if (!absolute.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new InvalidDataException("Path escapes the Unity project.");
        return absolute;
    }
    static void RejectLinks(string path, string root)
    {
        string full = Path.GetFullPath(path);
        if (full != root && !full.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new InvalidDataException("Path escapes the Unity project.");
        string current = full;
        while (current != root)
        {
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Symbolic links are not accepted in Atlas import paths.");
            current = Path.GetDirectoryName(current);
        }
    }
    static void WriteReport(string path, Report report)
    {
        RejectLinks(path, ProjectRoot);
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        string temporary = path + ".tmp";
        RejectLinks(temporary, ProjectRoot);
        File.WriteAllText(temporary, JsonUtility.ToJson(report, true));
        if (File.Exists(path)) File.Replace(temporary, path, null);
        else File.Move(temporary, path);
    }
    static void Progress(Report report, float percent, string stage)
    {
        // Weighted phases and item counts estimate progress, not elapsed time or an ETA.
        report.progress_percent = Mathf.Clamp(percent, 0, 100);
        report.progress_estimated = true;
        report.stage = stage;
        WriteReport(Path.Combine(ProjectRoot, "AtlasImports", "reports", report.job_id + ".json"), report);
    }
    static string Pipeline()
    {
        var pipeline = GraphicsSettings.currentRenderPipeline;
        if (pipeline == null) return "Built-in";
        string type = pipeline.GetType().Name;
        if (type.IndexOf("HDRender", StringComparison.OrdinalIgnoreCase) >= 0) return "HDRP";
        if (type.IndexOf("Universal", StringComparison.OrdinalIgnoreCase) >= 0) return "URP";
        return type;
    }
    static void Warn(Report report, string warning) { if (!report.warnings.Contains(warning)) report.warnings.Add(warning); }
    static void EnsureFolder(string path)
    {
        RejectLinks(Absolute(path), ProjectRoot);
        if (AssetDatabase.IsValidFolder(path)) return;
        string parent = path.Substring(0, path.LastIndexOf('/'));
        EnsureFolder(parent);
        if (string.IsNullOrEmpty(AssetDatabase.CreateFolder(parent, Path.GetFileName(path))))
            throw new IOException("Could not create Unity asset folder: " + path);
    }

    static void Import(Request request, Report report)
    {
        Progress(report, 10, "Importing files");
        // Refresh only after all requested paths and extensions have been checked.
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        string output = request.asset_folder + "/Generated";
        EnsureFolder(output);
        var maps = new List<Map>();
        bool hasHdri = false;
        int textureCount = request.files.Count(f => TextureExtensions.Contains(Path.GetExtension(f.path).ToLowerInvariant()));
        int textureIndex = 0;
        foreach (InputFile file in request.files.OrderBy(f => f.path, StringComparer.Ordinal))
        {
            string path = request.asset_folder + "/" + file.path;
            if (!TextureExtensions.Contains(Path.GetExtension(path).ToLowerInvariant())) continue;
            string role = Role(file.role, path);
            if (role == "unknown" && (request.kind ?? "").IndexOf("hdri", StringComparison.OrdinalIgnoreCase) >= 0
                && new[] { ".hdr", ".exr" }.Contains(Path.GetExtension(path).ToLowerInvariant())) role = "hdri";
            ConfigureTexture(path, role, report);
            report.textures.Add(path);
            Progress(report, 10 + 45f * (++textureIndex) / textureCount, "Importing textures (" + textureIndex + "/" + textureCount + ")");
            if (role == "hdri")
            {
                hasHdri = true;
                Warn(report, "HDRI imported as a cubemap; scene lighting unchanged.");
                continue;
            }
            if (role != "unknown" && role != "height") maps.Add(new Map { Path = path, Role = role, Key = SetKey(path),
                Priority = string.IsNullOrEmpty(file.role) || new[] { "texture", "dependency", "unknown", "map" }.Contains(file.role.ToLowerInvariant()) ? 0 : 1 });
            else Warn(report, role == "height" ? "Height/displacement texture retained; displacement is not enabled automatically." : "Unrecognized texture retained without material assignment: " + file.path);
        }
        Progress(report, 55, "Creating materials");
        var materials = BuildMaterials(maps, output, request, report);
        Progress(report, 75, "Importing models and animations");
        var convertedMaterials = new Dictionary<Material, Material>();
        int modelCount = request.files.Count(f => new[] { ".fbx", ".obj" }.Contains(Path.GetExtension(f.path).ToLowerInvariant()));
        int modelIndex = 0;
        foreach (InputFile file in request.files.OrderBy(f => f.path, StringComparer.Ordinal))
        {
            string extension = Path.GetExtension(file.path).ToLowerInvariant();
            if (extension == ".fbx" || extension == ".obj")
            {
                ImportModel(request.asset_folder + "/" + file.path, output, request, materials, convertedMaterials, report);
                Progress(report, 75 + 20f * (++modelIndex) / modelCount, "Importing models and animations (" + modelIndex + "/" + modelCount + ")");
            }
        }
        if ((request.kind ?? "").IndexOf("decal", StringComparison.OrdinalIgnoreCase) >= 0 && report.materials.Count > 0)
            Warn(report, "Decal material imported; a decal projector and gameplay placement were not created.");
        if (!hasHdri && report.prefabs.Count == 0 && report.materials.Count == 0 && report.animations.Count == 0)
            throw new InvalidDataException("No usable model, recognized material maps, or animation clips were found.");
    }

    static string Role(string explicitRole, string path)
    {
        string role = (explicitRole ?? "").ToLowerInvariant().Replace("_", "").Replace("-", "").Replace(" ", "");
        string inferred = Path.GetFileNameWithoutExtension(path).ToLowerInvariant();
        if (role == "" || role == "texture" || role == "unknown" || role == "map") role = inferred;
        if (role == "hdri" || role == "environment" || role == "environmentmap") return "hdri";
        if (Regex.IsMatch(role, @"base.?colou?r|albedo|diffuse|(?:^|[_-])(?:diff|colou?r)(?:$|[_-])")) return "albedo";
        if (role.Contains("normal") || Regex.IsMatch(role, @"(?:^|[_-])(?:nor|nrm)(?:[_-]?(?:gl|dx|opengl|directx))?(?:$|[_-])"))
            return role.Contains("dx") || role.Contains("directx") || Regex.IsMatch(inferred, @"(?:normal|nor|nrm)[_-]?(?:dx|directx)") ? "normalDX" : "normal";
        if (role.Contains("rough")) return "roughness";
        if (role.Contains("smooth") || role.Contains("gloss")) return "smoothness";
        if (role.Contains("metal")) return "metallic";
        if (role.Contains("specular")) return "specular";
        if (role == "ao" || role.Contains("occlusion") || Regex.IsMatch(role, @"(?:^|[_-])ao(?:$|[_-])")) return "ao";
        if (role.Contains("opacity") || role.Contains("alpha") || role.Contains("transparency")) return "opacity";
        if (role.Contains("emiss")) return "emission";
        if (role.Contains("displace") || role.Contains("height") || role.Contains("bump") || Regex.IsMatch(role, @"(?:^|[_-])disp(?:$|[_-])")) return "height";
        // A metadata label such as "texture/png" must not hide a descriptive filename.
        return role != inferred ? Role(null, path) : "unknown";
    }
    static string Normalize(string value) { return Regex.Replace(value.ToLowerInvariant(), @"[^a-z0-9]", ""); }
    static string SetKey(string path)
    {
        string name = Path.GetFileNameWithoutExtension(path);
        name = MapWords.Replace(name, "_");
        name = Regex.Replace(name, @"(?i)(?:^|[_ -])(?:\d+k|\d{3,5}x\d{3,5}|lod\d+|(?:u|v)\d+)(?=$|[_ -])", "_");
        return Normalize(name);
    }
    static void ConfigureTexture(string path, string role, Report report)
    {
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
        var importer = AssetImporter.GetAtPath(path) as TextureImporter;
        if (importer == null) throw new InvalidDataException("Unity cannot read texture: " + path);
        importer.textureType = role.StartsWith("normal", StringComparison.Ordinal) ? TextureImporterType.NormalMap : TextureImporterType.Default;
        importer.textureShape = role == "hdri" ? TextureImporterShape.TextureCube : TextureImporterShape.Texture2D;
        if (role == "hdri") importer.generateCubemap = TextureImporterGenerateCubemap.AutoCubemap;
        importer.sRGBTexture = role == "albedo" || role == "emission" || role == "specular" || role == "unknown";
        importer.maxTextureSize = 8192;
        if (role == "albedo") importer.alphaIsTransparency = true;
        var flip = typeof(TextureImporter).GetProperty("flipGreenChannel");
        if (flip != null && flip.CanWrite) flip.SetValue(importer, role == "normalDX", null);
        else if (role == "normalDX") Warn(report, "This Unity version cannot flip DirectX normal-map green channels automatically: " + path);
        importer.SaveAndReimport();
    }

    static List<MaterialSet> BuildMaterials(List<Map> maps, string output, Request request, Report report)
    {
        var result = new List<MaterialSet>();
        if (maps.Count == 0) return result;
        string shaderName = report.pipeline == "HDRP" ? "HDRP/Lit" : report.pipeline == "URP" ? "Universal Render Pipeline/Lit" : "Standard";
        if (report.pipeline != "HDRP" && report.pipeline != "URP" && report.pipeline != "Built-in")
            throw new InvalidDataException("Automatic materials do not support render pipeline: " + report.pipeline);
        Shader shader = Shader.Find(shaderName);
        if (shader == null) throw new InvalidDataException("Required shader is unavailable: " + shaderName);
        EnsureFolder(output + "/Materials");
        EnsureFolder(output + "/Textures");
        int sequence = 0;
        var groups = maps.GroupBy(m => m.Key).OrderBy(g => g.Key, StringComparer.Ordinal).ToArray();
        int groupIndex = 0;
        foreach (var group in groups)
        {
            Progress(report, 55 + 20f * groupIndex / groups.Length, "Creating materials (" + (++groupIndex) + "/" + groups.Length + ")");
            // Exporters often include byte-identical texture copies or both GL/DX normals.
            var chosen = new List<Map>();
            bool ambiguous = false;
            foreach (var roles in group.GroupBy(m => m.Role == "normalDX" ? "normal" : m.Role))
            {
                var candidates = roles.ToList();
                if (roles.Key == "normal" && candidates.Any(m => m.Role == "normal"))
                    candidates = candidates.Where(m => m.Role == "normal").ToList();
                int priority = candidates.Max(m => m.Priority);
                candidates = candidates.Where(m => m.Priority == priority).ToList();
                // Same-named files in different formats are export variants, not different material sets.
                if (candidates.Count > 1 && candidates.Select(m => Path.GetFileNameWithoutExtension(m.Path)).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 1)
                {
                    string[] formats = { ".png", ".tga", ".tiff", ".tif", ".jpg", ".jpeg", ".exr", ".hdr", ".bmp", ".psd" };
                    int format = candidates.Min(m => Array.IndexOf(formats, Path.GetExtension(m.Path).ToLowerInvariant()));
                    candidates = candidates.Where(m => Array.IndexOf(formats, Path.GetExtension(m.Path).ToLowerInvariant()) == format).ToList();
                }
                if (candidates.Count > 1 && candidates.Select(m => FileHash(m.Path)).Distinct().Count() > 1)
                { ambiguous = true; break; }
                chosen.Add(candidates[0]);
            }
            if (ambiguous)
            {
                Warn(report, "Ambiguous duplicate maps for texture set '" + group.Key + "'; automatic material creation skipped for this set.");
                continue;
            }
            var byRole = chosen.ToDictionary(m => m.Role, m => m.Path);
            Func<string, string> get = role => byRole.ContainsKey(role) ? byRole[role] : null;
            string stem = SafeName(string.IsNullOrEmpty(group.Key) ? request.name : group.Key) + "_" + (++sequence);
            bool specular = get("specular") != null && get("metallic") == null;
            Shader selectedShader = specular && report.pipeline == "Built-in" ? Shader.Find("Standard (Specular setup)") : shader;
            if (selectedShader == null) throw new InvalidDataException("Required Standard specular shader is unavailable.");
            var material = new Material(selectedShader) { name = stem };
            if (get("specular") != null && !specular) Warn(report, "Both metallic and specular maps supplied; metallic workflow takes precedence.");
            string baseMap = get("albedo");
            if (get("opacity") != null)
                baseMap = PackOpacity(baseMap, get("opacity"), output + "/Textures/" + stem + "_BaseColor.png", report);
            string normal = get("normal") ?? get("normalDX");
            string mask = null;
            if (get("roughness") != null || get("smoothness") != null || get("metallic") != null || get("ao") != null)
                mask = PackMask(get("metallic"), get("ao"), get("roughness"), get("smoothness"), output + "/Textures/" + stem + "_Mask.png", report);
            bool hdrp = report.pipeline == "HDRP";
            if (specular)
            {
                SetFloat(material, "_WorkflowMode", 0);
                SetFloat(material, "_MaterialID", 4); // HDRP Specular Color material type.
                SetColor(material, hdrp ? "_SpecularColor" : "_SpecColor", Color.white);
                if (hdrp)
                {
                    SetTexture(material, "_SpecularColorMap", get("specular"));
                    material.EnableKeyword("_MATERIAL_FEATURE_SPECULAR_COLOR"); material.EnableKeyword("_SPECULARCOLORMAP");
                }
                else
                {
                    string specMap = PackSpecular(get("specular"), get("roughness"), get("smoothness"), output + "/Textures/" + stem + "_SpecularGloss.png", report);
                    SetTexture(material, "_SpecGlossMap", specMap);
                    SetFloat(material, "_Smoothness", 1); SetFloat(material, "_GlossMapScale", 1);
                    if (report.pipeline == "URP") material.EnableKeyword("_SPECULAR_SETUP");
                    material.EnableKeyword(report.pipeline == "URP" ? "_METALLICSPECGLOSSMAP" : "_SPECGLOSSMAP");
                }
            }
            SetTexture(material, hdrp ? "_BaseColorMap" : report.pipeline == "URP" ? "_BaseMap" : "_MainTex", baseMap);
            SetColor(material, hdrp || report.pipeline == "URP" ? "_BaseColor" : "_Color", Color.white);
            SetTexture(material, hdrp ? "_NormalMap" : "_BumpMap", normal);
            if (normal != null) { material.EnableKeyword("_NORMALMAP"); if (hdrp) material.EnableKeyword("_NORMALMAP_TANGENT_SPACE"); }
            if (mask != null)
            {
                if (hdrp || !specular) SetTexture(material, hdrp ? "_MaskMap" : "_MetallicGlossMap", mask);
                SetFloat(material, "_Smoothness", 1);
                SetFloat(material, "_GlossMapScale", 1);
                SetFloat(material, "_SmoothnessTextureChannel", 0);
                SetFloat(material, "_MetallicRemapMin", 0); SetFloat(material, "_MetallicRemapMax", 1);
                SetFloat(material, "_SmoothnessRemapMin", 0); SetFloat(material, "_SmoothnessRemapMax", 1);
                SetFloat(material, "_AORemapMin", 0); SetFloat(material, "_AORemapMax", 1);
                if (hdrp || !specular) material.EnableKeyword(hdrp ? "_MASKMAP" : report.pipeline == "URP" ? "_METALLICSPECGLOSSMAP" : "_METALLICGLOSSMAP");
                if (!hdrp && get("ao") != null) { SetTexture(material, "_OcclusionMap", mask); material.EnableKeyword("_OCCLUSIONMAP"); }
            }
            else if (!specular) { SetFloat(material, "_Metallic", 0); SetFloat(material, "_Smoothness", .5f); SetFloat(material, "_Glossiness", .5f); }
            if (get("emission") != null)
            {
                SetTexture(material, hdrp ? "_EmissiveColorMap" : "_EmissionMap", get("emission"));
                SetColor(material, hdrp ? "_EmissiveColor" : "_EmissionColor", Color.white);
                SetColor(material, "_EmissiveColorLDR", Color.white);
                material.EnableKeyword(hdrp ? "_EMISSIVE_COLOR_MAP" : "_EMISSION");
                material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.BakedEmissive;
            }
            if (get("opacity") != null)
            {
                SetFloat(material, "_AlphaCutoffEnable", 1); SetFloat(material, "_AlphaClip", 1);
                SetFloat(material, "_AlphaCutoff", .5f); SetFloat(material, "_Cutoff", .5f); SetFloat(material, "_Mode", 1);
                material.EnableKeyword("_ALPHATEST_ON");
                material.SetOverrideTag("RenderType", "TransparentCutout"); material.renderQueue = (int)RenderQueue.AlphaTest;
                Warn(report, "Opacity maps use alpha clipping at 0.5; adjust the material for blended transparency if needed.");
            }
            ValidatePipelineMaterial(material, report);
            string path = AssetDatabase.GenerateUniqueAssetPath(output + "/Materials/" + stem + ".mat");
            AssetDatabase.CreateAsset(material, path);
            report.materials.Add(path);
            result.Add(new MaterialSet { Key = group.Key, Material = material });
        }
        if (result.Count == 0) throw new InvalidDataException("Recognized texture maps were found, but none could be assigned to an unambiguous material set.");
        return result;
    }
    static void SetFloat(Material material, string property, float value) { if (material.HasProperty(property)) material.SetFloat(property, value); }
    static string FileHash(string path)
    {
        using (var stream = File.OpenRead(Absolute(path)))
        using (var hash = SHA256.Create()) return Convert.ToBase64String(hash.ComputeHash(stream));
    }
    static void SetColor(Material material, string property, Color value) { if (material.HasProperty(property)) material.SetColor(property, value); }
    static void SetTexture(Material material, string property, string path)
    {
        if (path != null && material.HasProperty(property)) material.SetTexture(property, AssetDatabase.LoadAssetAtPath<Texture2D>(path));
    }
    static void ValidatePipelineMaterial(Material material, Report report)
    {
        if (report.pipeline != "HDRP") return;
        // Reflection keeps this helper compilable when HDRP is not installed.
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            var type = assembly.GetType("UnityEngine.Rendering.HighDefinition.HDMaterial");
            if (type == null) continue;
            var method = type.GetMethod("ValidateMaterial", new[] { typeof(Material) });
            if (method == null) continue;
            try { method.Invoke(null, new object[] { material }); }
            catch (Exception exception) { Warn(report, "HDRP material validation: " + exception.GetBaseException().Message); }
            return;
        }
        Warn(report, "HDRP material validation API is unavailable; verify material keywords in the Inspector.");
    }

    static Pixels ReadPixels(string path, Report report)
    {
        if (path == null) return null;
        var importer = AssetImporter.GetAtPath(path) as TextureImporter;
        if (importer == null) throw new InvalidDataException("Cannot read texture pixels: " + path);
        bool readable = importer.isReadable;
        int maxSize = importer.maxTextureSize;
        var compression = importer.textureCompression;
        try
        {
            var before = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (before != null && (before.width > MaxPackedSize || before.height > MaxPackedSize))
                Warn(report, "Generated packed textures are capped at 4096 pixels; source textures are retained at their original import resolution.");
            importer.isReadable = true;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.maxTextureSize = Math.Min(maxSize, MaxPackedSize);
            importer.SaveAndReimport();
            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (texture == null) throw new InvalidDataException("Texture could not be loaded: " + path);
            return new Pixels { Width = texture.width, Height = texture.height, Values = texture.GetPixels32() };
        }
        finally
        {
            importer.isReadable = readable;
            importer.textureCompression = compression;
            importer.maxTextureSize = maxSize;
            importer.SaveAndReimport();
        }
    }
    static void Dimensions(out int width, out int height, params Pixels[] values)
    {
        width = values.Where(p => p != null).Max(p => p.Width);
        height = values.Where(p => p != null).Max(p => p.Height);
    }
    static string PackMask(string metal, string ao, string rough, string smooth, string output, Report report)
    {
        Pixels m = ReadPixels(metal, report), a = ReadPixels(ao, report), r = ReadPixels(rough, report), s = ReadPixels(smooth, report);
        if (r != null && s != null) Warn(report, "Both roughness and smoothness supplied; roughness takes precedence.");
        int width, height; Dimensions(out width, out height, m, a, r, s);
        var pixels = new Color32[width * height];
        for (int y = 0; y < height; ++y)
            for (int x = 0; x < width; ++x)
                pixels[y * width + x] = new Color32(m == null ? (byte)0 : m.At(x, y, width, height).r,
                    a == null ? (byte)255 : a.At(x, y, width, height).r, 255,
                    r != null ? (byte)(255 - r.At(x, y, width, height).r) : s != null ? s.At(x, y, width, height).r : (byte)128);
        return SavePixels(output, pixels, width, height, false);
    }
    static string PackOpacity(string albedo, string opacity, string output, Report report)
    {
        Pixels color = ReadPixels(albedo, report), alpha = ReadPixels(opacity, report);
        int width, height; Dimensions(out width, out height, color, alpha);
        var pixels = new Color32[width * height];
        for (int y = 0; y < height; ++y)
            for (int x = 0; x < width; ++x)
            {
                var pixel = color == null ? new Color32(255, 255, 255, 255) : color.At(x, y, width, height);
                pixel.a = alpha.At(x, y, width, height).r;
                pixels[y * width + x] = pixel;
            }
        return SavePixels(output, pixels, width, height, true);
    }
    static string PackSpecular(string specular, string rough, string smooth, string output, Report report)
    {
        Pixels color = ReadPixels(specular, report), r = ReadPixels(rough, report), s = ReadPixels(smooth, report);
        int width, height; Dimensions(out width, out height, color, r, s);
        var pixels = new Color32[width * height];
        for (int y = 0; y < height; ++y)
            for (int x = 0; x < width; ++x)
            {
                var pixel = color.At(x, y, width, height);
                pixel.a = r != null ? (byte)(255 - r.At(x, y, width, height).r) : s != null ? s.At(x, y, width, height).r : (byte)128;
                pixels[y * width + x] = pixel;
            }
        return SavePixels(output, pixels, width, height, true, false);
    }
    static string SavePixels(string path, Color32[] pixels, int width, int height, bool color, bool transparency = true)
    {
        path = AssetDatabase.GenerateUniqueAssetPath(path);
        RejectLinks(Absolute(path), ProjectRoot);
        var texture = new Texture2D(width, height, TextureFormat.RGBA32, false, !color);
        try { texture.SetPixels32(pixels); texture.Apply(false); File.WriteAllBytes(Absolute(path), texture.EncodeToPNG()); }
        finally { Object.DestroyImmediate(texture); }
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
        var importer = (TextureImporter)AssetImporter.GetAtPath(path);
        importer.sRGBTexture = color;
        importer.alphaIsTransparency = color && transparency;
        importer.maxTextureSize = MaxPackedSize;
        importer.SaveAndReimport();
        return path;
    }

    static void ImportModel(string path, string output, Request request, List<MaterialSet> materials, Dictionary<Material, Material> convertedMaterials, Report report)
    {
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
        var importer = AssetImporter.GetAtPath(path) as ModelImporter;
        if (importer == null) throw new InvalidDataException("Unity cannot import model: " + path);
        importer.importAnimation = request.rig != "none";
        importer.animationType = request.rig == "none" ? ModelImporterAnimationType.None : ModelImporterAnimationType.Generic;
        importer.avatarSetup = request.rig == "none" ? ModelImporterAvatarSetup.NoAvatar : ModelImporterAvatarSetup.CreateFromThisModel;
        importer.optimizeGameObjects = false;
        importer.SaveAndReimport();
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(path);
        if (model == null) throw new InvalidDataException("Unity produced no model asset: " + path);
        bool hasGeometry = model.GetComponentsInChildren<Renderer>(true).Length > 0;
        bool hasSkin = model.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length > 0;
        bool fullBody = LooksLikeFullBody(model);
        bool arms = Regex.IsMatch(Path.GetFileNameWithoutExtension(path) + " " + request.name, @"(?i)(?:^|[ _-])(?:arms|fps|first[ _-]?person)(?:$|[ _-])");
        bool humanoid = hasGeometry && hasSkin && fullBody && !arms && request.rig != "generic" && request.rig != "none";
        if (request.rig == "humanoid" && !humanoid)
            Warn(report, "Humanoid requested but no recognizable complete body was found; Generic rig retained: " + Path.GetFileName(path));
        if (humanoid)
        {
            importer.animationType = ModelImporterAnimationType.Human;
            importer.SaveAndReimport();
            var avatar = AssetDatabase.LoadAllAssetsAtPath(path).OfType<Avatar>().FirstOrDefault();
            if (avatar == null || !avatar.isValid || !avatar.isHuman)
            {
                Warn(report, "Automatic Humanoid mapping failed validation; Generic rig retained: " + Path.GetFileName(path));
                importer.animationType = ModelImporterAnimationType.Generic;
                importer.SaveAndReimport();
            }
        }
        var clips = AssetDatabase.LoadAllAssetsAtPath(path).OfType<AnimationClip>().Where(c => !c.name.StartsWith("__preview__", StringComparison.Ordinal)).ToArray();
        if (!hasSkin && clips.Length == 0)
        {
            importer.animationType = ModelImporterAnimationType.None;
            importer.SaveAndReimport();
        }
        if (clips.Length > 0)
        {
            EnsureFolder(output + "/Animations");
            foreach (var clip in clips)
            {
                string clipPath = AssetDatabase.GenerateUniqueAssetPath(output + "/Animations/" + SafeName(Path.GetFileNameWithoutExtension(path) + "_" + clip.name) + ".anim");
                var independent = Object.Instantiate(clip);
                independent.name = clip.name;
                independent.hideFlags = HideFlags.None;
                AssetDatabase.CreateAsset(independent, clipPath);
                report.animations.Add(clipPath);
            }
            Warn(report, "Animation clips were imported; no Animator Controller was created. Generic clips require a compatible skeleton.");
        }
        if (!hasGeometry)
        {
            if (clips.Length == 0) Warn(report, "Model contains no renderable geometry or animation clips: " + Path.GetFileName(path));
            return;
        }
        EnsureFolder(output + "/Prefabs");
        // A preview scene avoids touching the user's open scenes, hierarchy or selection.
        var preview = EditorSceneManager.NewPreviewScene();
        GameObject instance = null;
        try
        {
            model = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            instance = (GameObject)PrefabUtility.InstantiatePrefab(model, preview);
            foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
            {
                var slots = renderer.sharedMaterials;
                for (int index = 0; index < slots.Length; ++index)
                {
                    Material replacement = MatchMaterial(slots[index], renderer.name, materials, request.material_bindings);
                    if (replacement == null && slots[index] != null)
                        replacement = ConvertEmbeddedMaterial(slots[index], output, convertedMaterials, report);
                    if (replacement != null) slots[index] = replacement;
                    else if (materials.Count > 0)
                        Warn(report, "Preserved unmatched material '" + (slots[index] == null ? "(empty)" : slots[index].name) + "' on " + renderer.name + ".");
                }
                renderer.sharedMaterials = slots;
            }
            string prefabPath = AssetDatabase.GenerateUniqueAssetPath(output + "/Prefabs/" + SafeName(Path.GetFileNameWithoutExtension(path)) + ".prefab");
            if (PrefabUtility.SaveAsPrefabAsset(instance, prefabPath) == null) throw new IOException("Could not save prefab: " + prefabPath);
            report.prefabs.Add(prefabPath);
        }
        finally { if (instance != null) Object.DestroyImmediate(instance); EditorSceneManager.ClosePreviewScene(preview); }
    }
    static Material ConvertEmbeddedMaterial(Material source, string output, Dictionary<Material, Material> cache, Report report)
    {
        if (report.pipeline == "Built-in") return source;
        Material existing;
        if (cache.TryGetValue(source, out existing)) return existing;
        string sourceShader = source.shader == null ? "(missing)" : source.shader.name;
        if (sourceShader != "Standard" && sourceShader != "Standard (Specular setup)")
        {
            Warn(report, "Preserved material '" + source.name + "' with shader '" + sourceShader + "'; automatic conversion supports Standard shaders only.");
            cache[source] = null;
            return null;
        }
        if (report.pipeline != "HDRP" && report.pipeline != "URP")
        {
            Warn(report, "Preserved embedded material; unsupported render pipeline: " + report.pipeline);
            cache[source] = null;
            return null;
        }
        bool hdrp = report.pipeline == "HDRP", specular = sourceShader == "Standard (Specular setup)";
        Shader shader = Shader.Find(hdrp ? "HDRP/Lit" : "Universal Render Pipeline/Lit");
        if (shader == null) throw new InvalidDataException("Target render-pipeline shader is unavailable.");
        var material = new Material(shader) { name = source.name + "_" + report.pipeline };
        Func<string, Texture> texture = property => source.HasProperty(property) ? source.GetTexture(property) : null;
        Func<string, float, float> scalar = (property, fallback) => source.HasProperty(property) ? source.GetFloat(property) : fallback;
        Func<string, Color, Color> color = (property, fallback) => source.HasProperty(property) ? source.GetColor(property) : fallback;
        Action<string, string> copyTexture = (from, to) =>
        {
            if (!source.HasProperty(from) || !material.HasProperty(to)) return;
            material.SetTexture(to, texture(from));
            material.SetTextureScale(to, source.GetTextureScale(from));
            material.SetTextureOffset(to, source.GetTextureOffset(from));
        };
        copyTexture("_MainTex", hdrp ? "_BaseColorMap" : "_BaseMap");
        SetColor(material, "_BaseColor", color("_Color", Color.white));
        copyTexture("_BumpMap", hdrp ? "_NormalMap" : "_BumpMap");
        SetFloat(material, hdrp ? "_NormalScale" : "_BumpScale", scalar("_BumpScale", 1));
        if (texture("_BumpMap") != null)
        {
            material.EnableKeyword("_NORMALMAP");
            if (hdrp) material.EnableKeyword("_NORMALMAP_TANGENT_SPACE");
        }
        string packedProperty = specular ? "_SpecGlossMap" : "_MetallicGlossMap";
        Texture packed = texture(packedProperty);
        float smoothness = packed == null ? scalar("_Glossiness", .5f) : scalar("_GlossMapScale", 1);
        SetFloat(material, "_Smoothness", smoothness);
        SetFloat(material, "_Metallic", scalar("_Metallic", 0));
        if (specular)
        {
            SetFloat(material, "_WorkflowMode", 0);
            SetFloat(material, "_MaterialID", 4);
            SetColor(material, hdrp ? "_SpecularColor" : "_SpecColor", color("_SpecColor", Color.white));
            copyTexture("_SpecGlossMap", hdrp ? "_SpecularColorMap" : "_SpecGlossMap");
            material.EnableKeyword(hdrp ? "_MATERIAL_FEATURE_SPECULAR_COLOR" : "_SPECULAR_SETUP");
            if (hdrp && packed != null) material.EnableKeyword("_SPECULARCOLORMAP");
        }
        if (hdrp)
        {
            // Standard's packed alpha is smoothness. Its green channel is not AO.
            if (packed != null)
            {
                copyTexture(packedProperty, "_MaskMap");
                SetFloat(material, "_MetallicRemapMin", 0); SetFloat(material, "_MetallicRemapMax", 1);
                SetFloat(material, "_SmoothnessRemapMin", 0); SetFloat(material, "_SmoothnessRemapMax", smoothness);
                SetFloat(material, "_AORemapMin", 1); SetFloat(material, "_AORemapMax", 1);
                material.EnableKeyword("_MASKMAP");
            }
            if (texture("_OcclusionMap") != null)
                Warn(report, "Embedded Standard material '" + source.name + "' converted to HDRP; its separate AO map requires manual Mask Map packing.");
            if (scalar("_SmoothnessTextureChannel", 0) > .5f)
                Warn(report, "Embedded material '" + source.name + "' uses albedo-alpha smoothness; verify HDRP smoothness after conversion.");
        }
        else
        {
            if (!specular) copyTexture("_MetallicGlossMap", "_MetallicGlossMap");
            if (packed != null) material.EnableKeyword("_METALLICSPECGLOSSMAP");
            copyTexture("_OcclusionMap", "_OcclusionMap");
            SetFloat(material, "_OcclusionStrength", scalar("_OcclusionStrength", 1));
            if (texture("_OcclusionMap") != null) material.EnableKeyword("_OCCLUSIONMAP");
            SetFloat(material, "_SmoothnessTextureChannel", scalar("_SmoothnessTextureChannel", 0));
            if (scalar("_SmoothnessTextureChannel", 0) > .5f) material.EnableKeyword("_SMOOTHNESS_TEXTURE_ALBEDO_CHANNEL_A");
        }
        copyTexture("_EmissionMap", hdrp ? "_EmissiveColorMap" : "_EmissionMap");
        Color emission = source.IsKeywordEnabled("_EMISSION") ? color("_EmissionColor", Color.black) : Color.black;
        SetColor(material, hdrp ? "_EmissiveColor" : "_EmissionColor", emission);
        SetColor(material, "_EmissiveColorLDR", emission);
        material.globalIlluminationFlags = source.globalIlluminationFlags;
        if (emission.maxColorComponent > 0) material.EnableKeyword(hdrp ? "_EMISSIVE_COLOR_MAP" : "_EMISSION");
        int mode = Mathf.RoundToInt(scalar("_Mode", 0));
        SetFloat(material, "_Cutoff", scalar("_Cutoff", .5f));
        SetFloat(material, "_AlphaCutoff", scalar("_Cutoff", .5f));
        if (mode == 1)
        {
            SetFloat(material, hdrp ? "_AlphaCutoffEnable" : "_AlphaClip", 1);
            material.EnableKeyword("_ALPHATEST_ON");
            material.SetOverrideTag("RenderType", "TransparentCutout"); material.renderQueue = (int)RenderQueue.AlphaTest;
        }
        else if (mode >= 2)
        {
            SetFloat(material, hdrp ? "_SurfaceType" : "_Surface", 1);
            SetFloat(material, hdrp ? "_BlendMode" : "_Blend", !hdrp && mode == 3 ? 1 : 0);
            SetFloat(material, "_SrcBlend", mode == 3 ? (int)BlendMode.One : (int)BlendMode.SrcAlpha);
            SetFloat(material, "_DstBlend", (int)BlendMode.OneMinusSrcAlpha);
            SetFloat(material, "_ZWrite", 0);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            if (!hdrp && mode == 3) material.EnableKeyword("_ALPHAPREMULTIPLY_ON");
            material.SetOverrideTag("RenderType", "Transparent"); material.renderQueue = (int)RenderQueue.Transparent;
        }
        ValidatePipelineMaterial(material, report);
        EnsureFolder(output + "/Materials");
        string path = AssetDatabase.GenerateUniqueAssetPath(output + "/Materials/" + SafeName(material.name) + ".mat");
        AssetDatabase.CreateAsset(material, path);
        report.materials.Add(path);
        cache[source] = material;
        return material;
    }
    static Material MatchMaterial(Material source, string renderer, List<MaterialSet> sets, MaterialBinding[] bindings)
    {
        if (sets.Count == 0) return null;
        if (source != null && bindings != null)
        {
            var bindingKeys = bindings.Where(b => b != null && Normalize(b.material ?? "") == Normalize(source.name))
                .Select(b => SetKey(b.texture_set ?? "")).Distinct().ToArray();
            var bound = sets.Where(s => bindingKeys.Contains(s.Key)).ToArray();
            if (bound.Length == 1) return bound[0].Material;
        }
        if (source != null)
        {
            var textureKeys = source.GetTexturePropertyNames().Select(p => source.GetTexture(p)).Where(t => t != null)
                .Select(t => SetKey(t.name)).Distinct().ToArray();
            var referenced = sets.Where(s => textureKeys.Contains(s.Key)).ToArray();
            if (referenced.Length == 1) return referenced[0].Material;
        }
        if (sets.Count == 1) return sets[0].Material;
        string materialName = source == null ? "" : SetKey(source.name);
        string meshName = SetKey(renderer);
        var matches = sets.Where(s => s.Key.Length > 0 && (s.Key == materialName || s.Key == meshName)).ToArray();
        if (matches.Length == 1) return matches[0].Material;
        // A unique descriptive containment match covers exporter-added material prefixes.
        matches = sets.Where(s => s.Key.Length >= 4 && ((materialName.Length >= 4 && (materialName.Contains(s.Key) || s.Key.Contains(materialName)))
            || (meshName.Length >= 4 && (meshName.Contains(s.Key) || s.Key.Contains(meshName))))).ToArray();
        return matches.Length == 1 ? matches[0].Material : null;
    }
    static bool LooksLikeFullBody(GameObject model)
    {
        string[] names = model.GetComponentsInChildren<Transform>(true).Select(t => Normalize(t.name)).ToArray();
        return names.Any(n => n.Contains("hips") || n.Contains("pelvis")) && names.Any(n => n.Contains("head"))
            && names.Any(n => n.Contains("leftupleg") || n.Contains("leftupperleg") || n.Contains("thighl") || n.Contains("lthigh"))
            && names.Any(n => n.Contains("rightupleg") || n.Contains("rightupperleg") || n.Contains("thighr") || n.Contains("rthigh"));
    }
    static string SafeName(string name)
    {
        string result = Regex.Replace(name ?? "Asset", @"[^A-Za-z0-9_-]", "_").Trim('_');
        return string.IsNullOrEmpty(result) ? "Asset" : result.Substring(0, Math.Min(100, result.Length));
    }
}
