using System;
using System.Linq;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

// Copy into a Unity Editor folder, then call Configure with the asset folder.
public static class AtlasFPSArmsImport
{
    public static Avatar Configure(string folder)
    {
        folder=folder.TrimEnd('/');string path=folder+"/FPS_Tactical_Arms.fbx";
        var model=AssetImporter.GetAtPath(path) as ModelImporter;
        if(model==null)throw new ArgumentException("FPS_Tactical_Arms.fbx not found in "+folder);
        model.animationType=ModelImporterAnimationType.Generic;
        model.avatarSetup=ModelImporterAvatarSetup.NoAvatar;
        model.optimizeBones=false;model.optimizeGameObjects=false;model.preserveHierarchy=true;
        model.importAnimation=false;model.isReadable=true;model.SaveAndReimport();
        var root=AssetDatabase.LoadAssetAtPath<GameObject>(path);
        var transforms=root.GetComponentsInChildren<Transform>(true);
        var human=new List<HumanBone>();
        Action<HumanBodyBones,string> map=(slot,name)=> {
            var bone=transforms.SingleOrDefault(t=>t.name=="mixamorig:"+name || t.name=="mixamorig_"+name || t.name==name);
            if(bone==null)throw new Exception("Missing bone "+name+"; present: "+string.Join(",",transforms.Select(t=>t.name)));
            human.Add(new HumanBone {boneName=bone.name,humanName=HumanTrait.BoneName[(int)slot],limit=new HumanLimit {useDefaultValues=true}});
        };
        map(HumanBodyBones.Hips,"Hips");map(HumanBodyBones.Spine,"Spine");map(HumanBodyBones.Chest,"Spine1");map(HumanBodyBones.UpperChest,"Spine2");map(HumanBodyBones.Neck,"Neck");map(HumanBodyBones.Head,"Head");
        foreach(string side in new[]{"Left","Right"}) {
            foreach(var pair in new[]{("UpperLeg","UpLeg"),("LowerLeg","Leg"),("Foot","Foot"),("Toes","ToeBase"),("Shoulder","Shoulder"),("UpperArm","Arm"),("LowerArm","ForeArm"),("Hand","Hand")})
                map((HumanBodyBones)Enum.Parse(typeof(HumanBodyBones),side+pair.Item1),side+pair.Item2);
            foreach(var finger in new[]{("Thumb","Thumb"),("Index","Index"),("Middle","Middle"),("Ring","Ring"),("Little","Pinky")}) {
                int segment=1;
                foreach(string joint in new[]{"Proximal","Intermediate","Distal"})
                    map((HumanBodyBones)Enum.Parse(typeof(HumanBodyBones),side+finger.Item1+joint),side+"Hand"+finger.Item2+(segment++));
            }
        }
        var description=model.humanDescription;
        description.human=human.ToArray();
        description.skeleton=transforms.Select(t=>new SkeletonBone{name=t.name,position=t.localPosition,rotation=t.localRotation,scale=t.localScale}).ToArray();
        description.upperArmTwist=.5f;description.lowerArmTwist=.5f;description.upperLegTwist=.5f;description.lowerLegTwist=.5f;description.armStretch=.05f;description.legStretch=.05f;
        model.humanDescription=description;model.animationType=ModelImporterAnimationType.Human;model.avatarSetup=ModelImporterAvatarSetup.CreateFromThisModel;model.SaveAndReimport();
        var avatar=AssetDatabase.LoadAllAssetsAtPath(path).OfType<Avatar>().Single();
        if(!avatar.isValid || !avatar.isHuman)throw new Exception("Humanoid Avatar failed validation");
        var clip=AssetImporter.GetAtPath(folder+"/Finger_Articulation_Test.fbx") as ModelImporter;
        if(clip!=null){clip.animationType=ModelImporterAnimationType.Human;clip.avatarSetup=ModelImporterAvatarSetup.CopyFromOther;clip.sourceAvatar=avatar;clip.importAnimation=true;var clips=clip.defaultClipAnimations;foreach(var c in clips){c.name="Finger_Articulation_Test";c.loopTime=true;}clip.clipAnimations=clips;clip.SaveAndReimport();}
        AssetDatabase.SaveAssets();return avatar;
    }
}
