using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class AtlasArmsVerify
{
    [Serializable] public class Report {
        public string unity_version; public bool avatar_valid; public bool avatar_humanoid;
        public int arm_meshes; public int vertices; public int triangles; public int mapped_fingers;
        public float direct_skin_deformation; public float animation_deformation;
        public string[] bones; public string[] animations;
    }
    public static void Run() {
        const string root="Assets/AtlasArms/";
        var avatar=AtlasFPSArmsImport.Configure(root);
        if(!avatar.isValid || !avatar.isHuman) throw new Exception("Invalid Humanoid Avatar");
        var animation=(ModelImporter)AssetImporter.GetAtPath(root+"Finger_Articulation_Test.fbx");
        animation.animationType=ModelImporterAnimationType.Human;
        animation.avatarSetup=ModelImporterAvatarSetup.CopyFromOther;
        animation.sourceAvatar=avatar; animation.importAnimation=true; animation.SaveAndReimport();
        var clips=AssetDatabase.LoadAllAssetsAtPath(root+"Finger_Articulation_Test.fbx").OfType<AnimationClip>().Where(c=>!c.name.StartsWith("__preview__")).ToArray();
        if(clips.Length!=1) throw new Exception("Expected one finger articulation clip");
        var go=(GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(root+"FPS_Tactical_Arms.fbx"));
        var animator=go.GetComponent<Animator>(); animator.avatar=avatar; animator.cullingMode=AnimatorCullingMode.AlwaysAnimate;
        var renderers=go.GetComponentsInChildren<SkinnedMeshRenderer>();
        if(renderers.Length!=2) throw new Exception("Expected two arm meshes");
        var before=Bake(renderers);
        var right=animator.GetBoneTransform(HumanBodyBones.RightIndexProximal);
        var left=animator.GetBoneTransform(HumanBodyBones.LeftIndexProximal);
        if(right==null || left==null) throw new Exception("Finger mapping missing");
        right.localRotation*=Quaternion.Euler(35,0,0);left.localRotation*=Quaternion.Euler(35,0,0);
        float direct=Delta(before,Bake(renderers));
        if(direct<.0001f)throw new Exception("Skin did not deform when fingers moved");
        var controller=AnimatorController.CreateAnimatorControllerAtPath(root+"GripValidation.controller");
        controller.AddMotion(clips[0]);animator.runtimeAnimatorController=controller;animator.Rebind();animator.Update(0);
        animator.Play(clips[0].name,0,0);animator.Update(0);var start=Bake(renderers);animator.Update(.6f);
        float movement=Delta(start,Bake(renderers));
        if(movement<.0001f)throw new Exception("Imported animation did not deform skin");
        int fingers=0;
        for(int b=(int)HumanBodyBones.LeftThumbProximal;b<=(int)HumanBodyBones.RightLittleDistal;b++) if(animator.GetBoneTransform((HumanBodyBones)b)!=null)fingers++;
        if(fingers!=30) throw new Exception("Expected all 30 finger joints");
        var report=new Report {unity_version=Application.unityVersion,avatar_valid=avatar.isValid,avatar_humanoid=avatar.isHuman,arm_meshes=renderers.Length,vertices=renderers.Sum(r=>r.sharedMesh.vertexCount),triangles=renderers.Sum(r=>r.sharedMesh.triangles.Length/3),mapped_fingers=fingers,direct_skin_deformation=direct,animation_deformation=movement,bones=go.GetComponentsInChildren<Transform>().Select(t=>t.name).ToArray(),animations=clips.Select(c=>c.name).ToArray()};
        var output=Path.Combine(Directory.GetParent(Application.dataPath).FullName,"unity-validation.json");
        File.WriteAllText(output,JsonUtility.ToJson(report,true));Debug.Log("ATLAS_ARMS_VERIFIED "+JsonUtility.ToJson(report));
        UnityEngine.Object.DestroyImmediate(go);AssetDatabase.SaveAssets();
    }
    static Vector3[] Bake(SkinnedMeshRenderer[] renderers) {
        return renderers.SelectMany(r=>{var mesh=new Mesh();r.BakeMesh(mesh);var v=mesh.vertices;UnityEngine.Object.DestroyImmediate(mesh);return v;}).ToArray();
    }
    static float Delta(Vector3[] a,Vector3[] b) {return a.Zip(b,(x,y)=>(x-y).magnitude).Max();}
}
